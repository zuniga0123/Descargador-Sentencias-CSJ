"""Líneas jurisprudenciales (método de López Medina) sobre la base de la app.

Dos capas, para que la IA no "acomode" las sentencias:

1. Capa determinista (sin IA), app/citas.py:
   - ingeniería reversa: a quién cita el punto arquimédico, a quién citan esas
     sentencias, y cuáles se repiten (nicho citacional y puntos nodales);
   - búsqueda prospectiva: sentencias posteriores que citan al punto
     arquimédico o a los puntos nodales;
   - puntos de contacto entre cortes, votos particulares, peso de cada sala,
     fecha de la última sentencia y estado de la línea.
2. Capa interpretativa (IA con control):
   - planteamiento: problema jurídico con dos polos (la persona lo ajusta);
   - ficha neutra de cada sentencia (app/fichas.py, sin conocer la línea);
   - ubicación entre los polos (1 a 5) con el apartado y una cita literal que
     la app verifica contra el texto; marca "no fija línea";
   - clasificación (fundadora, hito, confirmadora…), evolución de subreglas y
     balance, citando solo sentencias de la línea.
"""

from __future__ import annotations

import re
import threading
import traceback
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import busqueda, casos, citas, fichas, ia, precedentes

HILOS = 6
LOTE = 5
TAMANO = {"normal": 30, "amplia": 60}
CLASES = {
    "fundadora": "Fundadora de línea",
    "hito_consolidadora": "Hito consolidadora",
    "hito_modificadora": "Hito modificadora (de cambio)",
    "hito_reconceptualizadora": "Hito reconceptualizadora",
    "confirmadora": "Confirmadora de principio",
    "no_fija_linea": "No fija línea",
}
USOS = {"fundamento", "reiteracion", "mencion", "distincion", "apartamiento"}


# ---------- Peso de cada fuente (determinista) ----------

def peso(f: dict) -> dict:
    sala = (f.get("sala") or "").lower()
    if f["corte_clave"] == "cc":
        if f["radicado"].startswith("SU"):
            return {"nivel": 3, "etiqueta": "Sala Plena (unificación)",
                    "nota": "Unifica la jurisprudencia de tutela; prevalece sobre las sentencias T."}
        if f["radicado"].startswith("C"):
            return {"nivel": 3, "etiqueta": "Sala Plena (constitucionalidad)",
                    "nota": "Control abstracto con efectos generales."}
        return {"nivel": 2, "etiqueta": "Sala de Revisión",
                "nota": "Precedente en tutela; subordinado a las SU y a la Sala Plena."}
    if "descongesti" in sala:
        return {"nivel": 1, "etiqueta": "Sala de Descongestión Laboral",
                "nota": "Aplica la jurisprudencia de la Sala permanente y no puede cambiarla (Ley 1781 de 2016)."}
    return {"nivel": 3, "etiqueta": "Sala de Casación Laboral (permanente)",
            "nota": "Fija la jurisprudencia de la Sala Laboral y es la única que puede cambiarla."}


# ---------- Utilidades ----------

def resolver_entrada(texto: str) -> tuple[str, str] | None:
    """Interpreta 'T-076/24', 'SU-061 de 2023', 'SL1152-2023', 'sentencia C-355 de 2006'…"""
    texto = (texto or "").strip()
    if not texto:
        return None
    for corte in ("cc", "csj"):
        if busqueda.id_por_radicado(corte, texto):
            return corte, texto
    m = citas.RE_CC.search(texto)
    if m:
        rad = citas.normalizar_cc(*m.groups())
        if busqueda.id_por_radicado("cc", rad):
            return "cc", rad
    m = citas.RE_CSJ.search(texto)
    if m:
        rad = f"{m.group(1).upper()}{m.group(2)}-{m.group(3)}"
        if busqueda.id_por_radicado("csj", rad):
            return "csj", rad
    return None


class _Uso:
    def __init__(self) -> None:
        self.entrada = 0
        self.salida = 0
        self._lock = threading.Lock()

    def sumar(self, uso: dict) -> None:
        with self._lock:
            self.entrada += uso.get("entrada", 0)
            self.salida += uso.get("salida", 0)


SISTEMA = (
    "Eres un investigador de jurisprudencia colombiana que construye líneas jurisprudenciales con el método de "
    "Diego López Medina. Eres riguroso: no atribuyes a una sentencia lo que no dice y copias las citas literalmente. "
    "Respondes únicamente con un objeto JSON válido, en español."
)


def _llamar(prompt: str, uso: _Uso, max_tokens: int) -> dict:
    datos, u = ia.chat_json([{"role": "system", "content": SISTEMA}, {"role": "user", "content": prompt}],
                            max_tokens=max_tokens)
    uso.sumar(u)
    return datos


def _avance(lid: int, paso: str, progreso: int, uso: _Uso | None = None) -> None:
    campos = {"paso": paso, "progreso": progreso}
    if uso:
        campos.update(tokens_entrada=uso.entrada, tokens_salida=uso.salida)
    casos.actualizar_linea(lid, **campos)


def _ficha_corta(f: dict, ficha: dict | None) -> str:
    cabeza = f"{f['radicado']} ({f.get('ano')}) · {f['corte']} · {f.get('sala') or ''}"
    if not ficha:
        return cabeza
    r = ficha["resultado"]
    reglas = " | ".join(f"({x['papel']}) {x['regla']}" for x in ficha["reglas"][:3])
    return (f"{cabeza}\n  Hechos: {' | '.join(ficha['hechos'][:6])}\n  Problema: {ficha['problema_juridico']}\n"
            f"  Resultado: {r['efecto']} (favoreció a {r['favorece_a']})\n  Reglas: {reglas}")


def candidatas_por_corte(consultas: list[str], corte: str, desde, hasta, limite: int = 12) -> list[int]:
    caso = {"desde": desde, "hasta": hasta, "recientes": 1}
    return precedentes._lista_por_corte(consultas, corte, caso, set())[:limite]


# ---------- Paso 1: planteamiento ----------

def _prompt_planteamiento_tema(texto: str) -> str:
    return f"""Una persona quiere construir una línea jurisprudencial sobre este asunto:

«{texto}»

Formula el problema jurídico de la línea según López Medina: una pregunta en nivel medio de abstracción, descrita en términos fácticos (no meramente conceptual), con dos respuestas extremas (polos).

Devuelve este JSON:
{{
  "problema": "la pregunta, que empiece con ¿ y termine con ?",
  "polo_a": "respuesta extrema afirmativa, en una frase",
  "polo_b": "respuesta extrema negativa, en una frase",
  "patron_factico": "los hechos que hacen análogas las sentencias de esta línea",
  "tema": "tema", "subtema": "subtema",
  "consultas": ["4 a 6 consultas para un buscador de texto completo: \\"frase exacta\\", O entre alternativas, prefijo*; con el vocabulario de la Sala Laboral y el de la Corte Constitucional"]
}}"""


def _prompt_planteamiento_sentencia(f: dict, ficha: dict) -> str:
    return f"""Una persona aporta esta sentencia como punto de partida (punto arquimédico) de una línea jurisprudencial.

{_ficha_corta(f, ficha)}

Formula el problema jurídico de la línea según López Medina: una pregunta en nivel medio de abstracción, en términos fácticos, que esta sentencia resuelve, con dos respuestas extremas (polos).

Devuelve este JSON:
{{
  "problema": "la pregunta, que empiece con ¿ y termine con ?",
  "polo_a": "respuesta extrema afirmativa, en una frase",
  "polo_b": "respuesta extrema negativa, en una frase",
  "patron_factico": "los hechos que hacen análogas las sentencias de esta línea",
  "tema": "tema", "subtema": "subtema",
  "consultas": ["4 a 6 consultas para un buscador de texto completo: \\"frase exacta\\", O entre alternativas, prefijo*; con el vocabulario de la Sala Laboral y el de la Corte Constitucional"]
}}"""


def _prompt_arquimedica(plan: dict, corte: str, bloques: list[str]) -> str:
    nombre = "la Corte Constitucional" if corte == "cc" else "la Corte Suprema de Justicia, Sala Laboral"
    return f"""Problema de la línea: {plan['problema']}
Patrón fáctico: {plan.get('patron_factico') or '—'}

Candidatas de {nombre} (fichas elaboradas sin conocer la línea):
{chr(10).join(bloques)}

Elige el punto arquimédico de {nombre}: la sentencia MÁS RECIENTE que tenga el mismo patrón fáctico y resuelva el problema.
Devuelve este JSON: {{"arquimedica": "radicado exacto de la lista", "razon": "por qué, en una o dos frases", "otras_validas": ["radicados de la lista que también tienen el patrón fáctico"]}}"""


def plantear(lid: int) -> None:
    linea = casos.obtener_linea(lid)
    plan = linea["planteamiento"]
    uso = _Uso()
    con_ia = ia.estado()["activa"]
    cortes = plan.get("cortes") or ["csj", "cc"]
    plan["cortes"] = cortes
    arquimedicas: dict[str, str] = dict(plan.get("arquimedicas") or {})

    if linea["modo"] == "sentencia":
        resuelta = resolver_entrada(linea["entrada"])
        if not resuelta:
            raise ia.ErrorIA(f"No se encontró la sentencia «{linea['entrada']}» en la base. Revise el radicado "
                             "(por ejemplo T-076-24, SU061-23 o SL1152-2023).", accionable=True)
        corte, rad = resuelta
        arquimedicas[corte] = rad
        if corte not in cortes:
            cortes.append(corte)
        plan["sentencia_aportada"] = {"corte": corte, "radicado": rad}
        if con_ia:
            _avance(lid, "La IA está leyendo la sentencia aportada", 15, uso)
            pid = busqueda.id_por_radicado(corte, rad)
            ficha = fichas.elaborar(pid, uso.sumar)
            propuesta = _llamar(_prompt_planteamiento_sentencia(busqueda.ficha(pid), ficha), uso, 1500)
        else:
            propuesta = {}
    else:
        if con_ia:
            _avance(lid, "La IA está formulando el problema jurídico y los polos", 15, uso)
            propuesta = _llamar(_prompt_planteamiento_tema(linea["entrada"]), uso, 1500)
        else:
            propuesta = {"problema": linea["entrada"], "consultas": [linea["entrada"]]}

    for k in ("problema", "polo_a", "polo_b", "patron_factico", "tema", "subtema"):
        if not plan.get(k) and propuesta.get(k):
            plan[k] = str(propuesta[k])[:600]
    consultas = [str(q) for q in propuesta.get("consultas") or [] if str(q).strip()][:6]
    if not consultas:
        base_texto = f"{plan.get('problema') or ''} {plan.get('patron_factico') or ''} {linea['entrada']}"
        if linea["modo"] == "sentencia" and plan.get("sentencia_aportada"):
            aportada = plan["sentencia_aportada"]
            pid_ap = busqueda.id_por_radicado(aportada["corte"], aportada["radicado"])
            f = busqueda.ficha(pid_ap)
            if aportada["corte"] == "cc":
                # Las titulaciones de la relatoría son frases jurídicas que aparecen en los textos.
                frases = [f'"{t}"' for t in (f.get("subtema"), f.get("tema")) if t and not str(t).startswith(("Otros", "Sin subtema"))]
                consultas = frases[:2]
            else:
                # En la Corte Suprema se toman las palabras del análisis de la Corte, no de los hechos.
                base_texto += " " + fichas.extracto_amplio(busqueda.leer_texto(pid_ap), "csj")["analisis"]
        claves = precedentes.palabras_clave(base_texto, 8, min_df=150, max_frac=0.25, min_tf=2) if not consultas else []
        if claves:  # las más distintivas juntas y, como alternativa, cualquiera de ellas
            consultas = [" ".join(claves[:3]), " O ".join(claves)]
    plan["consultas"] = consultas

    # Candidatas y punto arquimédico de cada corte que no lo tenga.
    _avance(lid, "Buscando el punto arquimédico de cada corte", 40, uso)
    plan["candidatas"] = {}
    for corte in cortes:
        ids = candidatas_por_corte(consultas, corte, plan.get("desde"), plan.get("hasta"), 10) if consultas else []
        datos = [busqueda.ficha(i) for i in ids]
        plan["candidatas"][corte] = [{"radicado": d["radicado"], "ano": d["ano"], "sala": d["sala"], "tipo": d["tipo"]} for d in datos]
        if corte in arquimedicas or not ids:
            continue
        if con_ia:
            elegidas = ids[:6]
            fichas_c, _ = fichas.elaborar_varias(elegidas, uso.sumar)
            bloques = [_ficha_corta(busqueda.ficha(i), fichas_c.get(i)) for i in elegidas]
            r = _llamar(_prompt_arquimedica(plan, corte, bloques), uso, 600)
            rad = str(r.get("arquimedica") or "").strip()
            validos = {busqueda.ficha(i)["radicado"] for i in elegidas}
            if rad in validos:
                arquimedicas[corte] = rad
                plan.setdefault("razon_arquimedica", {})[corte] = str(r.get("razon") or "")[:400]
        if corte not in arquimedicas:  # sin IA: la más reciente entre las 5 más pertinentes
            arquimedicas[corte] = max(datos[:5], key=lambda d: (d["ano"] or 0, d.get("fecha") or ""))["radicado"]
    plan["arquimedicas"] = arquimedicas
    casos.actualizar_linea(lid, planteamiento=plan, estado="planteada", paso="Listo para revisar", progreso=100,
                           tokens_entrada=uso.entrada, tokens_salida=uso.salida)


# ---------- Paso 2: construcción ----------

def _clave(corte: str, rad: str) -> tuple[str, str]:
    return corte, rad


def nicho(arquimedica: tuple[str, str], profundidad: int, cortes: set[str]) -> dict:
    """Ingeniería reversa determinista desde el punto arquimédico."""
    niveles: dict[tuple, int] = {arquimedica: 0}
    aristas: list[dict] = []
    frontera = [arquimedica]
    indegree: Counter = Counter()
    no_en_base: Counter = Counter()
    for nivel in range(1, profundidad + 1):
        conteo: Counter = Counter()
        detalles: dict[tuple, list] = defaultdict(list)
        for origen in frontera:
            for c in citas.citadas_por(*origen):
                destino = (c["destino_corte"], c["destino_radicado"])
                if destino == origen:
                    continue
                if citas.resolver(*destino) is None:
                    no_en_base[destino] += 1
                    continue
                conteo[destino] += 1
                detalles[destino].append((origen, c))
        if nivel == 1:
            elegidos = list(conteo)
        else:  # niveles siguientes: solo las que citan al menos dos sentencias del nicho
            elegidos = [d for d, n in conteo.most_common() if n >= 2][:25]
        nueva = []
        for destino in elegidos:
            for origen, c in detalles[destino]:
                aristas.append({"origen": origen, "destino": destino, **{k: c[k] for k in
                                ("veces", "en_nota", "en_consideraciones", "en_antecedentes", "en_salvamento")}})
            indegree[destino] += conteo[destino]
            if destino not in niveles:
                niveles[destino] = nivel
                nueva.append(destino)
        frontera = [d for d in nueva if d[0] in cortes or nivel == 1]
    return {"niveles": niveles, "aristas": aristas, "indegree": indegree, "no_en_base": no_en_base}


def prospectivas(semillas: list[tuple[str, str]], ano_desde: int | None, limite: int = 12) -> list[tuple[tuple, int, int]]:
    """Sentencias posteriores que citan a las semillas. Devuelve (clave, n.º de semillas citadas, cita al arquimédico)."""
    puntaje: Counter = Counter()
    al_primero: dict[tuple, int] = {}
    for i, s in enumerate(semillas):
        for c in citas.que_la_citan(*s):
            if c["en_salvamento"] and c["veces"] == c["en_salvamento"]:
                continue
            if ano_desde and (c["origen_ano"] or 0) < ano_desde:
                continue
            k = (c["origen_corte"], c["origen_radicado"])
            puntaje[k] += 1
            if i == 0:
                al_primero[k] = 1
    orden = sorted(puntaje, key=lambda k: (-puntaje[k] - al_primero.get(k, 0), k))
    return [(k, puntaje[k], al_primero.get(k, 0)) for k in orden[:limite]]


def _contextos(origen: tuple[str, str], destinos: set[tuple[str, str]], maximo: int = 3) -> list[dict]:
    """Fragmentos literales donde `origen` cita a sentencias de `destinos`."""
    pid = busqueda.id_por_radicado(*origen)
    if not pid:
        return []
    texto = busqueda.leer_texto(pid)
    salida, vistos = [], set()
    for c in citas.extraer(texto, origen[1]):
        k = (c.corte, c.radicado)
        if k in destinos and k not in vistos and c.seccion != "salvamento":
            vistos.add(k)
            salida.append({"destino": c.radicado, "corte": c.corte, "seccion": c.seccion, "en_nota": c.en_nota,
                           "contexto": citas.contexto(texto, c, 360)})
            if len(salida) >= maximo:
                break
    return salida


def _prompt_ubicacion(plan: dict, bloques: list[str]) -> str:
    return f"""PROBLEMA DE LA LÍNEA: {plan['problema']}
Polo A (posición 1): {plan.get('polo_a') or '—'}
Polo B (posición 5): {plan.get('polo_b') or '—'}
Patrón fáctico: {plan.get('patron_factico') or '—'}

SENTENCIAS (fichas neutras y fragmentos literales donde citan a otras de la línea)
{chr(10).join(bloques)}

Para cada sentencia devuelve su ubicación en la línea. JSON:
{{"ubicaciones": [{{
  "ref": "L1",
  "aborda_problema": true,
  "posicion": 3,
  "justificacion": "por qué esa posición, a partir de lo que decidió (máximo 50 palabras)",
  "fundamento": "apartado o numeral donde la Corte lo dice (p. ej. 'fundamento 5.3', 'Consideraciones, 4'), como aparece en el texto",
  "cita": "copia literal de la sentencia que sustenta la ubicación (15 a 60 palabras)",
  "no_fija_linea": false,
  "motivo_no_fija": "",
  "subregla": "Cuando [supuesto], [conducta] está [ordenada/prohibida/permitida] porque [razón]",
  "usos": [{{"rad": "radicado citado", "uso": "fundamento | reiteracion | mencion | distincion | apartamiento"}}]
}}]}}

Reglas:
- "posicion": 1 = polo A, 5 = polo B, 3 = intermedia; 2 y 4 = inclinada hacia un polo con matices. Ubícala por lo que DECIDIÓ y su ratio, no por lo que menciona.
- "aborda_problema": false si la sentencia no resuelve este problema (entonces posicion = null).
- "no_fija_linea": true si decidió por técnica de casación, por razones procesales o por hechos particulares (p. ej., una confesión) y su doctrina aparece solo de paso; explica en "motivo_no_fija".
- "cita": cópiala exactamente de la ficha o de los fragmentos; se verificará contra el texto completo.
- "usos": cómo usa cada sentencia de la línea que cita, según los fragmentos literales: "fundamento" si la aplica para decidir, "reiteracion" si repite su regla, "mencion" si la nombra de paso, "distincion" si dice que no aplica por hechos distintos, "apartamiento" si se separa de ella."""


def _prompt_balance(plan: dict, corte: str, filas: list[str]) -> str:
    nombre = "Corte Constitucional" if corte == "cc" else "Corte Suprema de Justicia, Sala Laboral"
    return f"""LÍNEA DE LA {nombre.upper()}
Problema: {plan['problema']}
Polo A (1): {plan.get('polo_a') or '—'} · Polo B (5): {plan.get('polo_b') or '—'}

Sentencias en orden cronológico (posición, sala, número de veces que la citan las demás de la línea, subregla):
{chr(10).join(filas)}

Clasifica cada sentencia y haz el balance de la línea. Devuelve este JSON:
{{
  "clasificacion": [{{"rad": "radicado", "clase": "fundadora | hito_consolidadora | hito_modificadora | hito_reconceptualizadora | confirmadora | no_fija_linea", "razon": "máximo 30 palabras"}}],
  "dominante": "radicado de la sentencia que contiene el criterio vigente",
  "doctrina_vigente": "la posición vigente, 40 a 100 palabras, con [radicado] por afirmación",
  "evolucion": "cómo cambian las subreglas de una sentencia a otra, 60 a 150 palabras, con [radicado]",
  "vacios": "qué falta para completar la línea (p. ej., la fundadora puede ser anterior a la base)"
}}
Reglas: cita solo radicados de la lista. "fundadora" es la primera sentencia de la lista que resuelve el problema (adviértelo en "vacios" si pudo haber anteriores). Las hito son las que cambian o consolidan notablemente el precedente; las confirmadoras repiten una tesis previa. Una sentencia de Sala de Descongestión no puede ser modificadora. Una marcada como "no fija línea" conserva esa clase."""


def _prompt_cruce(plan: dict, resumenes: dict[str, str], contactos: list[str]) -> str:
    return f"""Problema: {plan['problema']}

Balance de la línea de cada corte:
{chr(10).join(f'- {k}: {v}' for k, v in resumenes.items())}

Puntos de contacto (fragmentos literales donde una corte cita a la otra):
{chr(10).join(contactos) or '(ninguno)'}

Devuelve este JSON:
{{"relacion": "cómo se relacionan las dos líneas: coinciden, una adoptó el criterio de la otra, chocan; 50 a 120 palabras con [radicado]",
  "subregla_de_derecho": "la subregla que resulta de la línea, en forma deóntica: Cuando…, … porque…"}}
Cita solo radicados que aparezcan arriba."""


def estado_linea(puntos: list[tuple[str, int]]) -> dict:
    """Estado según las posiciones en el tiempo. puntos: (fecha AAAA-MM-DD o año, posición 1-5)."""
    puntos = sorted(p for p in puntos if p[1])
    if len(puntos) < 2:
        return {"estado": "insuficiente", "detalle": "Hay muy pocas sentencias ubicadas para describir la línea.",
                "ultima": puntos[-1][0] if puntos else None}
    lado = lambda pos: "A" if pos <= 2 else "B" if pos >= 4 else "M"
    ultima = puntos[-1][0]
    ano_ultima = int(str(ultima)[:4])
    recientes = [p for p in puntos if int(str(p[0])[:4]) >= ano_ultima - 4]
    previas = [p for p in puntos if p not in recientes]
    lados_rec = Counter(lado(p[1]) for p in recientes)
    if lados_rec["A"] and lados_rec["B"]:
        return {"estado": "en tensión", "ultima": ultima,
                "detalle": f"En los últimos cinco años hay sentencias en ambos polos ({lados_rec['A']} hacia A, {lados_rec['B']} hacia B)."}
    mayor_rec = lados_rec.most_common(1)[0][0]
    if previas:
        mayor_prev = Counter(lado(p[1]) for p in previas).most_common(1)[0][0]
        if {mayor_rec, mayor_prev} == {"A", "B"}:
            primera = next(p[0] for p in recientes if lado(p[1]) == mayor_rec)
            return {"estado": "cambio reciente", "ultima": ultima,
                    "detalle": f"Las sentencias recientes (desde {primera}) se ubican en el polo opuesto al de las anteriores."}
    return {"estado": "pacífica", "ultima": ultima,
            "detalle": "Las sentencias se mantienen del mismo lado de la línea."}


_RE_CITA_LINEA = re.compile(r"\[([^\[\]]{3,40})\]")


def _marcar(texto: str, permitidos: set[str]) -> str:
    def r(m):
        rad = m.group(1).strip()
        if rad in permitidos or not precedentes._RE_RADICADO.match(rad):
            return m.group(0)
        return f"[{rad} — no está en la línea: verifíquela]"
    return _RE_CITA_LINEA.sub(r, texto or "")


def construir(lid: int, amplitud: str = "normal") -> None:
    linea = casos.obtener_linea(lid)
    plan = linea["planteamiento"]
    uso = _Uso()
    con_ia = ia.estado()["activa"]
    if not citas.disponible():
        raise ia.ErrorIA("Falta preparar la red de citas. Pulse «Preparar red de citas» en la pestaña Líneas "
                         "(tarda unos minutos y se hace una sola vez).", accionable=True)
    cortes = plan.get("cortes") or ["csj", "cc"]
    profundidad = max(1, min(3, int(plan.get("profundidad") or 2)))
    limite = TAMANO.get(amplitud, 30)
    desde, hasta = plan.get("desde"), plan.get("hasta")

    # 1. Ingeniería reversa y prospectiva por corte (determinista).
    _avance(lid, "Ingeniería reversa: siguiendo las citas desde el punto arquimédico", 5)
    prioridad: Counter = Counter()
    origen_nodo: dict[tuple, set] = defaultdict(set)
    niveles_corte: dict[str, dict] = {}
    aristas: list[dict] = []
    no_en_base: Counter = Counter()
    for corte in cortes:
        rad = (plan.get("arquimedicas") or {}).get(corte)
        if not rad or not busqueda.id_por_radicado(corte, rad):
            continue
        arq = (corte, rad)
        n = nicho(arq, profundidad, set(cortes))
        niveles_corte[corte] = {f"{k[0]}|{k[1]}": v for k, v in n["niveles"].items()}
        aristas += n["aristas"]
        no_en_base.update(n["no_en_base"])
        prioridad[arq] += 1000
        origen_nodo[arq].add("arquimédica")
        for k, nivel in n["niveles"].items():
            if nivel:
                prioridad[k] += 10 * n["indegree"][k] + (6 if nivel == 1 else 2)
                origen_nodo[k].add(f"nivel {nivel}")
        nodales = [k for k, _ in n["indegree"].most_common(5)]
        ano_arq = busqueda.ficha(busqueda.id_por_radicado(*arq))["ano"]
        for k, n_sem, al_arq in prospectivas([arq] + nodales, ano_arq):
            if citas.resolver(*k) is None:
                continue
            prioridad[k] += 4 * n_sem + 3 * al_arq
            origen_nodo[k].add("prospectiva")
        if plan.get("consultas"):
            for i in candidatas_por_corte(plan["consultas"], corte, desde, hasta, 6):
                f = busqueda.ficha(i)
                k = (f["corte_clave"], f["radicado"])
                prioridad[k] += 2
                origen_nodo[k].add("búsqueda")
    if not prioridad:
        raise ia.ErrorIA("No hay punto arquimédico válido. Elija una sentencia de partida para al menos una corte.",
                         accionable=True)

    def en_rango(k):
        f = busqueda.ficha(busqueda.id_por_radicado(*k)) if busqueda.id_por_radicado(*k) else None
        if not f or f["corte_clave"] not in cortes:
            return False
        return (not desde or (f["ano"] or 0) >= desde) and (not hasta or (f["ano"] or 0) <= hasta)

    # Cupo por corte: cada línea tiene su propio espacio (las tutelas no desplazan a la Sala Laboral).
    ordenadas = [k for k in sorted(prioridad, key=lambda k: -prioridad[k]) if en_rango(k)]
    por_corte_k = {c: [k for k in ordenadas if k[0] == c] for c in cortes}
    elegidas, i = [], 0
    while len(elegidas) < limite and any(i < len(v) for v in por_corte_k.values()):
        for c in cortes:
            if i < len(por_corte_k[c]) and len(elegidas) < limite:
                elegidas.append(por_corte_k[c][i])
        i += 1
    claves = set(elegidas)
    ids = {k: busqueda.id_por_radicado(*k) for k in elegidas}
    datos = {k: busqueda.ficha(ids[k]) for k in elegidas}

    # Citas dentro de la línea (red completa entre las elegidas) y contactos entre cortes.
    internas: dict[tuple, list] = defaultdict(list)
    for k in elegidas:
        for c in citas.citadas_por(*k):
            d = (c["destino_corte"], c["destino_radicado"])
            if d in claves and d != k:
                internas[k].append({"destino": d, **{x: c[x] for x in ("veces", "en_nota", "en_consideraciones",
                                                                         "en_antecedentes", "en_salvamento")}})
    citada_por_n = Counter(d["destino"] for lst in internas.values() for d in lst if d["en_salvamento"] < d["veces"])

    # 2. Fichas neutras y ubicación (IA).
    fichas_por: dict[tuple, dict] = {}
    ubicaciones: dict[tuple, dict] = {}
    if con_ia:
        def avance_fichas(h, t):
            _avance(lid, f"La IA está leyendo las sentencias sin conocer la línea ({h} de {t})", 10 + int(40 * h / t), uso)
        fichas_ids, errores_f = fichas.elaborar_varias(list(ids.values()), uso.sumar, avance_fichas)
        fichas_por = {k: fichas_ids[ids[k]] for k in elegidas if ids[k] in fichas_ids}

        refs = {f"L{n}": k for n, k in enumerate(elegidas, 1)}
        lotes = [list(refs.items())[i : i + LOTE] for i in range(0, len(refs), LOTE)]

        def ubicar(lote):
            bloques = []
            for ref, k in lote:
                ctx = _contextos(k, claves - {k})
                frag = "\n".join(f"  Cita a {x['destino']} ({x['seccion']}{', nota al pie' if x['en_nota'] else ''}): «{x['contexto']}»" for x in ctx)
                bloques.append(f"[{ref}] {_ficha_corta(datos[k], fichas_por.get(k))}" + (f"\n{frag}" if frag else ""))
            r = _llamar(_prompt_ubicacion(plan, bloques), uso, 900 * len(lote) + 500)
            return lote, ia.lista_de(r, "ubicaciones")

        hechos_l = 0
        _avance(lid, "La IA está ubicando cada sentencia entre los polos", 52, uso)
        with ThreadPoolExecutor(max_workers=HILOS) as grupo:
            for futuro in as_completed([grupo.submit(ubicar, l) for l in lotes]):
                try:
                    lote, lista = futuro.result()
                except ia.ErrorIA as exc:
                    ia.registrar(f"Línea {lid}, ubicación: {exc}")
                    continue
                validos = dict(lote)
                for u in lista:
                    if isinstance(u, dict) and str(u.get("ref", "")).strip("[] ") in validos:
                        ubicaciones[validos[str(u["ref"]).strip("[] ")]] = u
                hechos_l += 1
                _avance(lid, f"Ubicando sentencias entre los polos ({min(hechos_l * LOTE, len(elegidas))} de {len(elegidas)})",
                        52 + int(28 * hechos_l / len(lotes)), uso)

    # 3. Armar cada sentencia de la línea con controles deterministas.
    sentencias = []
    for k in elegidas:
        f, pid = datos[k], ids[k]
        texto = busqueda.leer_texto(pid)
        u = ubicaciones.get(k) or {}
        verificador = fichas.Verificador(texto)
        cita = str(u.get("cita") or "").strip()
        try:
            posicion = int(u["posicion"]) if u.get("posicion") not in (None, "", "null") and u.get("aborda_problema", True) else None
            posicion = posicion if posicion in (1, 2, 3, 4, 5) else None
        except (TypeError, ValueError):
            posicion = None
        usos = []
        for x in u.get("usos") or []:
            if isinstance(x, dict) and x.get("uso") in USOS:
                usos.append({"rad": str(x.get("rad") or "")[:40], "uso": x["uso"]})
        sentencias.append({
            **{c: f.get(c) for c in ("corte", "corte_clave", "sala", "tipo", "radicado", "ano", "fecha", "ponente")},
            "id": pid,
            "peso": peso(f),
            "origen": sorted(origen_nodo[k]),
            "nivel": min((v for c in niveles_corte.values() for kk, v in c.items() if kk == f"{k[0]}|{k[1]}"), default=None),
            "citada_en_linea": citada_por_n[k],
            "cita_a": [{"radicado": d["destino"][1], "corte": d["destino"][0], "veces": d["veces"], "en_nota": d["en_nota"],
                        "en_consideraciones": d["en_consideraciones"], "en_antecedentes": d["en_antecedentes"],
                        "en_salvamento": d["en_salvamento"]} for d in internas[k]],
            "votos": citas.votos_particulares(texto),
            "ficha": fichas_por.get(k),
            "aborda_problema": bool(u.get("aborda_problema", True)) if u else None,
            "posicion": posicion,
            "justificacion": str(u.get("justificacion") or "")[:500],
            "fundamento": str(u.get("fundamento") or "")[:120],
            "cita": cita[:700],
            "cita_verificada": verificador.verificar(cita) if cita else False,
            "no_fija_linea": bool(u.get("no_fija_linea")),
            "motivo_no_fija": str(u.get("motivo_no_fija") or "")[:300],
            "subregla": str(u.get("subregla") or "")[:600],
            "usos": usos,
            "clase": "no_fija_linea" if u.get("no_fija_linea") else None,
        })
    sentencias.sort(key=lambda s: (s.get("fecha") or str(s.get("ano") or ""), s["radicado"]))

    # 4. Por corte: estado, advertencias, clasificación y balance.
    por_corte: dict[str, dict] = {}
    contactos = []
    for s in sentencias:
        for d in s["cita_a"]:
            if d["corte"] != s["corte_clave"]:
                contactos.append({"origen": s["radicado"], "origen_corte": s["corte_clave"], "destino": d["radicado"],
                                  "destino_corte": d["corte"]})
    # Contactos con sentencias de la otra corte fuera de la línea (p. ej., una T que cita SL no elegidas).
    for s in sentencias:
        otras = {(c["destino_corte"], c["destino_radicado"]) for c in citas.citadas_por(s["corte_clave"], s["radicado"])
                 if c["destino_corte"] != s["corte_clave"] and c["en_salvamento"] < c["veces"]}
        ya = {(x["destino_corte"], x["destino"]) for x in contactos if x["origen"] == s["radicado"]}
        for d in sorted(otras - ya)[:4]:
            if citas.resolver(*d):
                contactos.append({"origen": s["radicado"], "origen_corte": s["corte_clave"], "destino": d[1], "destino_corte": d[0],
                                  "fuera_de_linea": True})
    for x in contactos:
        ctx = _contextos((x["origen_corte"], x["origen"]), {(x["destino_corte"], x["destino"])}, 1)
        x["contexto"] = ctx[0]["contexto"] if ctx else ""
        x["en_nota"] = ctx[0]["en_nota"] if ctx else False
    contactos = [x for x in contactos if x["contexto"]][:30]

    _avance(lid, "Clasificando las sentencias y haciendo el balance", 82, uso)
    permitidos_total = {s["radicado"] for s in sentencias}
    trabajos = {}
    for corte in cortes:
        propias = [s for s in sentencias if s["corte_clave"] == corte]
        if not propias:
            continue
        puntos = [(s.get("fecha") or str(s["ano"]), s["posicion"]) for s in propias if s["posicion"] and not s["no_fija_linea"]]
        advertencias = []
        if corte == "csj":
            fijan = [s for s in propias if s["posicion"] and not s["no_fija_linea"]]
            if fijan and all(s["peso"]["nivel"] == 1 for s in fijan):
                advertencias.append("Todas las sentencias ubicadas son de Salas de Descongestión, que aplican pero no pueden fijar ni "
                                    "cambiar la jurisprudencia: más que una línea, muestran cómo se aplica la de la Sala permanente. "
                                    "Busque las sentencias de la Sala de Casación Laboral permanente.")
            elif any(s["peso"]["nivel"] == 1 for s in fijan):
                advertencias.append("Las sentencias de Descongestión aplican la jurisprudencia de la Sala permanente: no pueden marcar un cambio de línea.")
        if corte == "cc" and any(s["radicado"].startswith("SU") for s in propias):
            advertencias.append("Hay sentencias de unificación (SU): prevalecen sobre las de Sala de Revisión.")
        if not con_ia:
            advertencias.append("Sin IA: se muestra la red de citas, pero no la ubicación entre polos ni la clasificación.")
        sin_verif = [s["radicado"] for s in propias if s["posicion"] and not s["cita_verificada"]]
        if sin_verif:
            advertencias.append(f"La ubicación de {', '.join(sin_verif[:6])} no tiene una cita verificada en el texto: revísela antes de usarla.")
        votos = Counter(v["magistrado"] for s in propias for v in s["votos"] if v["tipo"] == "salvamento")
        por_corte[corte] = {
            "arquimedica": (plan.get("arquimedicas") or {}).get(corte),
            "estado": estado_linea(puntos),
            "ultima_sentencia": max((s.get("fecha") or str(s["ano"]) for s in propias), default=None),
            "advertencias": advertencias,
            "disidencias_recurrentes": [{"magistrado": m, "salvamentos": n} for m, n in votos.most_common() if n >= 2],
            "n": len(propias),
        }
        if con_ia and any(s["posicion"] for s in propias):
            filas = [f"- {s['radicado']} ({s.get('fecha') or s['ano']}) · {s['peso']['etiqueta']} · posición "
                     f"{s['posicion'] if s['posicion'] else 'no aborda'}{' · NO FIJA LÍNEA: ' + s['motivo_no_fija'] if s['no_fija_linea'] else ''}"
                     f" · citada {s['citada_en_linea']} veces en la línea · subregla: {s['subregla'] or '—'}" for s in propias]
            trabajos[corte] = filas

    def balance(corte):
        return corte, _llamar(_prompt_balance(plan, corte, trabajos[corte]), uso, 3500)

    with ThreadPoolExecutor(max_workers=HILOS) as grupo:
        for futuro in as_completed([grupo.submit(balance, c) for c in trabajos]):
            try:
                corte, b = futuro.result()
            except ia.ErrorIA as exc:
                ia.registrar(f"Línea {lid}, balance: {exc}")
                continue
            permitidos = {s["radicado"] for s in sentencias if s["corte_clave"] == corte}
            for c in ia.lista_de(b, "clasificacion"):
                if not isinstance(c, dict):
                    continue
                s = next((x for x in sentencias if x["radicado"] == str(c.get("rad", "")).strip() and x["corte_clave"] == corte), None)
                clase = str(c.get("clase") or "").strip()
                if s and clase in CLASES and not s["no_fija_linea"]:
                    if clase == "hito_modificadora" and s["peso"]["nivel"] == 1:
                        clase = "confirmadora"  # Descongestión no puede cambiar la jurisprudencia
                    s["clase"] = clase
                    s["razon_clase"] = str(c.get("razon") or "")[:300]
            dominante = str(b.get("dominante") or "").strip()
            por_corte[corte].update({
                "dominante": dominante if dominante in permitidos else None,
                "doctrina_vigente": _marcar(str(b.get("doctrina_vigente") or ""), permitidos),
                "evolucion": _marcar(str(b.get("evolucion") or ""), permitidos),
                "vacios": str(b.get("vacios") or "")[:600],
            })
            # El estado se recalcula sin las que no fijan línea.
            puntos = [(s.get("fecha") or str(s["ano"]), s["posicion"]) for s in sentencias
                      if s["corte_clave"] == corte and s["posicion"] and s.get("clase") != "no_fija_linea"]
            por_corte[corte]["estado"] = estado_linea(puntos)

    relacion = {}
    if con_ia and len([c for c in por_corte if por_corte[c].get("doctrina_vigente")]) == 2:
        _avance(lid, "Relación entre las líneas de las dos cortes", 95, uso)
        nombres = {"cc": "Corte Constitucional", "csj": "Corte Suprema, Sala Laboral"}
        try:
            r = _llamar(_prompt_cruce(plan, {nombres[c]: por_corte[c]["doctrina_vigente"] for c in por_corte},
                                      [f"- {x['origen']} cita {x['destino']}: «{x['contexto'][:300]}»" for x in contactos[:12]]),
                        uso, 1500)
            relacion = {"relacion": _marcar(str(r.get("relacion") or ""), permitidos_total | {x["destino"] for x in contactos}),
                        "subregla_de_derecho": str(r.get("subregla_de_derecho") or "")[:700]}
        except ia.ErrorIA as exc:
            ia.registrar(f"Línea {lid}, cruce: {exc}")

    resultado = {
        "version": 1,
        "con_ia": con_ia,
        "sentencias": sentencias,
        "por_corte": por_corte,
        "contactos": contactos,
        "relacion": relacion,
        "no_en_base": [{"corte": k[0], "radicado": k[1], "veces": n} for k, n in no_en_base.most_common(30)],
        "profundidad": profundidad,
    }
    casos.actualizar_linea(lid, resultado=resultado, estado="lista", paso="Listo", progreso=100,
                           tokens_entrada=uso.entrada, tokens_salida=uso.salida)


# ---------- Ejecución en segundo plano ----------

def _en_hilo(lid: int, funcion, *args) -> None:
    def trabajo():
        try:
            funcion(lid, *args)
        except ia.ErrorIA as exc:
            ia.registrar(f"Línea {lid}: {exc}")
            mensaje = str(exc) if getattr(exc, "accionable", False) else (
                "No se pudo completar la línea. Intente de nuevo; si se repite, envíe el archivo datos/registro_ia.log.")
            casos.actualizar_linea(lid, estado="error", error=mensaje, paso="Error")
        except Exception as exc:
            traceback.print_exc()
            ia.registrar(f"Línea {lid}: error inesperado {exc}")
            casos.actualizar_linea(lid, estado="error", error=f"Error inesperado: {exc}", paso="Error")

    threading.Thread(target=trabajo, daemon=True, name=f"linea-{lid}").start()


def iniciar_planteamiento(lid: int) -> None:
    casos.actualizar_linea(lid, estado="planteando", paso="Iniciando", progreso=2, error=None)
    _en_hilo(lid, plantear)


def iniciar_construccion(lid: int, amplitud: str = "normal") -> None:
    casos.actualizar_linea(lid, estado="construyendo", paso="Iniciando", progreso=2, error=None)
    _en_hilo(lid, construir, amplitud)


def con_ids(linea: dict) -> dict:
    """Actualiza los ids (cambian al reconstruir la base)."""
    for s in (linea.get("resultado") or {}).get("sentencias") or []:
        s["id"] = busqueda.id_por_radicado(s["corte_clave"], s["radicado"])
    return linea
