"""Asignación del área del derecho (primer nivel de carpetas) para la Corte
Constitucional.

La Relatoría publica tema/subtema oficiales ("titulaciones"), pero no un área
tradicional del derecho. Se asigna con reglas de palabras clave sobre las
titulaciones, el TEMA y el RESUMEN de la Relatoría (reglas tomadas del
proyecto anterior, Descargador-Sentencias-CC). Las palabras se buscan como
palabras completas para que, por ejemplo, "pos" no coincida con "posible".
"""

from __future__ import annotations

import re
import unicodedata

CONTROL_ABSTRACTO = "Control de Constitucionalidad Abstracto"
SIN_CLASIFICAR = "Otros - Sin clasificar"

# En empate gana el área que aparece primero.
REGLAS: dict[str, list[str]] = {
    'Derecho a la Salud': [
        'derecho a la salud',
        'eps',
        'pos',
        'plan obligatorio de salud',
        'sistema general de seguridad social en salud',
        'sgsss',
        'tutela en salud',
        'tratamiento medico',
        'medicamento',
        'entidad promotora de salud',
        'ips',
        'enfermedad huerfana',
        'cirugia',
        'diagnostico medico',
        'incapacidad medica',
        'historia clinica',
    ],
    'Derechos Étnicos y Consulta Previa': [
        'consulta previa',
        'comunidad indigena',
        'pueblo indigena',
        'comunidad afrodescendiente',
        'comunidad negra',
        'territorio ancestral',
        'jurisdiccion especial indigena',
        'cabildo indigena',
        'consejo comunitario',
        'resguardo indigena',
        'minorias etnicas',
        'identidad cultural',
        'pueblo rrom',
        'comunidad rom',
        'diversidad etnica',
    ],
    'Derecho de Familia y Derechos de Niños, Niñas y Adolescentes': [
        'derechos de los ninos',
        'derechos de las ninas',
        'interes superior del menor',
        'custodia',
        'patria potestad',
        'adopcion',
        'alimentos',
        'cuota alimentaria',
        'violencia intrafamiliar',
        'union marital de hecho',
        'regimen de visitas',
        'menor de edad',
        'adolescente',
        'filiacion',
        'divorcio',
        'custodia y cuidado personal',
    ],
    'Derecho Penal y Sistema Acusatorio': [
        'sistema penal acusatorio',
        'proceso penal',
        'accion de tutela contra sentencia penal',
        'fiscalia general de la nacion',
        'medida de aseguramiento',
        'detencion preventiva',
        'principio de legalidad penal',
        'delito',
        'juez de control de garantias',
        'recurso de apelacion penal',
        'casacion penal',
        'libertad condicional',
        'sistema carcelario',
        'sistema penitenciario',
        'extradicion',
    ],
    'Derecho Laboral y Seguridad Social': [
        'derecho al trabajo',
        'pension',
        'reliquidacion pensional',
        'seguridad social',
        'fondo de pensiones',
        'regimen de transicion',
        'contrato de trabajo',
        'despido',
        'estabilidad laboral reforzada',
        'fuero sindical',
        'prima de servicios',
        'cesantias',
        'indemnizacion laboral',
        'invalidez',
        'sustitucion pensional',
        'riesgos laborales',
        'colpensiones',
    ],
    'Derecho Constitucional Económico': [
        'derecho de propiedad',
        'regimen tributario',
        'impuesto',
        'servicio publico domiciliario',
        'libertad economica',
        'libre competencia',
        'expropiacion',
        'tarifa',
        'contrato estatal',
        'contratacion publica',
        'propiedad privada',
        'derecho a la vivienda',
        'arrendamiento',
        'tasa',
        'contribucion',
        'regalias',
    ],
    'Derecho Administrativo y Función Pública': [
        'funcion publica',
        'acto administrativo',
        'carrera administrativa',
        'servidor publico',
        'concurso de meritos',
        'entidad territorial',
        'control disciplinario',
        'procuraduria general de la nacion',
        'contraloria general de la republica',
        'responsabilidad del estado',
        'nulidad y restablecimiento del derecho',
        'silencio administrativo',
    ],
    'Control de Constitucionalidad Abstracto': [
        'demanda de inconstitucionalidad',
        'control de constitucionalidad',
        'cosa juzgada constitucional',
        'inexequible',
        'exequible',
        'vicio de procedimiento',
        'vicio de forma',
        'juicio de constitucionalidad',
        'norma demandada',
        'unidad normativa',
        'control automatico',
        'ley estatutaria',
        'decreto legislativo',
        'estado de excepcion',
    ],
    'Derechos Fundamentales y Debido Proceso': [
        'debido proceso',
        'accion de tutela',
        'derecho de peticion',
        'derecho a la vida',
        'libertad de expresion',
        'habeas corpus',
        'habeas data',
        'derecho a la intimidad',
        'libertad religiosa',
        'libertad de cultos',
        'igualdad y no discriminacion',
        'libre desarrollo de la personalidad',
        'derecho de acceso a la administracion de justicia',
        'accion de cumplimiento',
        'accion popular',
        'derecho a la honra',
    ],
}


def _normalizar(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode("ascii")


_PATRONES = {area: [re.compile(rf"\b{re.escape(k)}\b") for k in kws] for area, kws in REGLAS.items()}


def asignar_area(texto: str, tipo: str) -> str:
    """texto: titulaciones + TEMA + RESUMEN de la Relatoría. tipo: T, C, SU o A."""
    texto = _normalizar(texto)
    puntajes = {area: sum(len(p.findall(texto)) for p in patrones) for area, patrones in _PATRONES.items()}
    mejor = max(puntajes, key=puntajes.get)
    if puntajes[mejor] > 0:
        return mejor
    return CONTROL_ABSTRACTO if tipo == "C" else SIN_CLASIFICAR
