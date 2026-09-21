"""Clasificación por reglas de palabras clave sobre tema/subtema de Derecho
Laboral y Seguridad Social (Sala de Casación Laboral / Sala de Descongestión
Laboral de la CSJ).

La CSJ (a diferencia de la Corte Constitucional) no expone tema/subtema
oficial como metadato consultable en su API — se confirmó en la exploración
técnica de septiembre 2026 (ver README). Por eso se clasifica aplicando
reglas de palabras clave sobre el texto completo de la providencia y las
normas citadas (leyesOArticulos). No hay paso de clasificación por IA en
esta fase por decisión explícita (sin presupuesto de API).

Los casos sin ningún término coincidente quedan en "Otros / Sin
clasificar" para revisión manual, tal como propone el brief.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

OTROS_TEMA = "Otros - Sin clasificar"
OTROS_SUBTEMA = "Sin subtema"

# tema -> {subtema -> [palabras/frases clave]}
TAXONOMIA: dict[str, dict[str, list[str]]] = {
    "Contrato de Trabajo y Contrato Realidad": {
        "Contrato realidad y subordinación": [
            "contrato realidad",
            "principio de primacia de la realidad",
            "subordinacion laboral",
            "elementos del contrato de trabajo",
            "relacion laboral encubierta",
        ],
        "Tipos de contrato y vinculación": [
            "contrato de trabajo a termino fijo",
            "contrato de trabajo a termino indefinido",
            "contrato de prestacion de servicios",
            "cooperativa de trabajo asociado",
            "intermediacion laboral",
            "tercerizacion laboral",
        ],
        "Contrato de trabajo (general)": [
            "contrato de trabajo",
            "contrato laboral",
        ],
    },
    "Pensiones": {
        "Pensión de vejez": [
            "pension de vejez",
            "regimen de prima media",
            "regimen de ahorro individual",
            "indemnizacion sustitutiva de la pension de vejez",
            "bono pensional",
        ],
        "Pensión de invalidez": [
            "pension de invalidez",
            "perdida de capacidad laboral",
            "junta de calificacion de invalidez",
            "estado de invalidez",
        ],
        "Pensión de sobrevivientes": [
            "pension de sobrevivientes",
            "sustitucion pensional",
            "causantes de la pension",
            "companero permanente",
            "beneficiarios de la pension",
        ],
        "Régimen de transición y RAIS/RPM": [
            "regimen de transicion",
            "rais",
            "colpensiones",
            "fondo de pensiones",
            "traslado de regimen pensional",
        ],
    },
    "Seguridad Social en Salud y Riesgos Laborales": {
        "Salud (EPS)": [
            "eps",
            "sistema general de seguridad social en salud",
            "incapacidad medica",
            "licencia de maternidad",
        ],
        "Riesgos laborales / ARL": [
            "riesgos laborales",
            "accidente de trabajo",
            "enfermedad laboral",
            "arl",
            "administradora de riesgos laborales",
        ],
    },
    "Estabilidad Laboral Reforzada y Fuero": {
        "Fuero de salud / debilidad manifiesta": [
            "estabilidad laboral reforzada",
            "debilidad manifiesta",
            "condicion de salud",
            "despido discriminatorio",
        ],
        "Fuero de maternidad": [
            "fuero de maternidad",
            "estado de embarazo",
            "licencia de maternidad",
        ],
        "Fuero sindical": [
            "fuero sindical",
            "permiso sindical",
        ],
    },
    "Terminación del Contrato, Despido e Indemnizaciones": {
        "Despido sin justa causa": [
            "despido sin justa causa",
            "despido injusto",
            "indemnizacion por despido",
        ],
        "Justa causa y terminación unilateral": [
            "justa causa",
            "terminacion unilateral del contrato",
            "abandono del cargo",
        ],
        "Renuncia y retiro voluntario": [
            "renuncia",
            "retiro voluntario",
        ],
    },
    "Salario, Prestaciones Sociales e Indemnización Moratoria": {
        "Salario y factores salariales": [
            "salario",
            "factor salarial",
            "salario en especie",
        ],
        "Prestaciones sociales": [
            "cesantias",
            "prima de servicios",
            "vacaciones",
            "prestaciones sociales",
        ],
        "Indemnización moratoria": [
            "indemnizacion moratoria",
            "sancion moratoria",
        ],
    },
    "Derecho Colectivo del Trabajo": {
        "Convenciones y pactos colectivos": [
            "convencion colectiva",
            "pacto colectivo",
        ],
        "Sindicatos y negociación colectiva": [
            "sindicato",
            "negociacion colectiva",
            "pliego de peticiones",
        ],
        "Huelga": [
            "huelga",
            "cese de actividades",
        ],
    },
    "Prescripción y Caducidad": {
        "Prescripción de derechos laborales": [
            "prescripcion",
            "termino prescriptivo",
        ],
        "Caducidad": [
            "caducidad de la accion",
        ],
    },
    "Aspectos Procesales del Recurso de Casación Laboral": {
        "Técnica de casación": [
            "tecnica de casacion",
            "error de hecho",
            "error de derecho",
            "violacion de la ley sustancial",
            "via directa",
            "via indirecta",
        ],
        "Admisibilidad y procedencia": [
            "recurso de casacion",
            "causal de casacion",
            "sentencia recurrida",
        ],
    },
}

# Señal adicional: normas citadas (leyesOArticulos) frecuentemente asociadas
# a un tema, para reforzar la clasificación cuando el texto es ambiguo.
NORMA_A_TEMA: dict[str, str] = {
    "ley 100 de 1993": "Pensiones",
    "decreto 758 de 1990": "Pensiones",
    "ley 797 de 2003": "Pensiones",
    "ley 860 de 2003": "Pensiones",
    "ley 361 de 1997": "Estabilidad Laboral Reforzada y Fuero",
    "ley 50 de 1990": "Contrato de Trabajo y Contrato Realidad",
    "codigo sustantivo del trabajo": "Contrato de Trabajo y Contrato Realidad",
    "ley 100 de 1993 riesgos": "Seguridad Social en Salud y Riesgos Laborales",
}


def _normalizar(texto: str) -> str:
    texto = texto.lower()
    reemplazos = str.maketrans("áéíóúñ", "aeioun")
    return texto.translate(reemplazos)


@dataclass
class Clasificacion:
    area: str = "Derecho Laboral y Seguridad Social"
    tema: str = OTROS_TEMA
    subtema: str = OTROS_SUBTEMA
    puntaje: int = 0


def clasificar(texto_markdown: str, leyes_o_articulos: list[str] | None = None) -> Clasificacion:
    texto_norm = _normalizar(texto_markdown)
    leyes_norm = [_normalizar(x) for x in (leyes_o_articulos or [])]

    puntajes_tema: dict[str, int] = {}
    mejor_subtema_por_tema: dict[str, tuple[str, int]] = {}

    for tema, subtemas in TAXONOMIA.items():
        total_tema = 0
        mejor_subtema = (OTROS_SUBTEMA, 0)
        for subtema, keywords in subtemas.items():
            puntaje_subtema = 0
            for kw in keywords:
                kw_norm = _normalizar(kw)
                puntaje_subtema += len(re.findall(re.escape(kw_norm), texto_norm))
            total_tema += puntaje_subtema
            if puntaje_subtema > mejor_subtema[1]:
                mejor_subtema = (subtema, puntaje_subtema)
        puntajes_tema[tema] = total_tema
        mejor_subtema_por_tema[tema] = mejor_subtema

    for norma_clave, tema in NORMA_A_TEMA.items():
        if any(norma_clave in ley for ley in leyes_norm):
            puntajes_tema[tema] = puntajes_tema.get(tema, 0) + 3

    if not puntajes_tema or max(puntajes_tema.values()) == 0:
        return Clasificacion()

    mejor_tema = max(puntajes_tema, key=puntajes_tema.get)
    subtema, _ = mejor_subtema_por_tema.get(mejor_tema, (OTROS_SUBTEMA, 0))
    return Clasificacion(
        tema=mejor_tema,
        subtema=subtema if subtema != OTROS_SUBTEMA else OTROS_SUBTEMA,
        puntaje=puntajes_tema[mejor_tema],
    )
