"""Buscador de precedentes y análisis de un caso (versión 2).

Con DeepSeek configurado:
  1. Planteamiento: la IA lee el caso y devuelve el problema jurídico, los
     hechos determinantes y las CUESTIONES (temas jurídicos) que el caso debe
     resolver, cada una con sus consultas de búsqueda.
  2. Candidatas: por cada cuestión y por cada corte se corren las consultas
     en la base local, con cupos separados por corte (para que las tutelas no
     desplacen a la Sala Laboral) y, si se pide, prioridad a las recientes.
  3. Fichas neutras (app/fichas.py): la IA lee cada candidata SIN conocer el
     caso: hechos, resultado, si decide el fondo y reglas con citas literales
     que se verifican contra el texto.
  4. Comparación: con las fichas (no con el texto crudo) la IA compara hecho
     por hecho con el caso, sin poder cambiar el resultado ni las reglas.
     La similitud de hechos la calcula la app a partir de esa tabla.
  5. Por cuestión: qué dicen los precedentes, argumentos para la parte
     representada, objeciones, puntos por verificar y vacíos.
  6. Revisión crítica: otra pasada busca argumentos que perjudiquen a la
     propia parte o que atribuyan a una sentencia algo que no dice.
  Las citas a radicados que no están entre las revisadas se marcan.

Sin IA: palabras clave del caso -> búsqueda con los mismos cupos -> orden por
coincidencia, sin explicaciones.
"""

from __future__ import annotations

import math
import re
import threading
import time
import traceback
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import busqueda, casos, fichas, ia

VERSION = 2
HILOS = 6
LOTE_COMPARACION = 5
CANDIDATAS = {"normal": 40, "amplia": 80}
POR_CONSULTA = 30          # resultados que se piden a cada consulta
UMBRAL_PRECEDENTE = 40     # pertinencia mínima para mostrarla como precedente
MAX_POR_CUESTION = 8       # precedentes que se le dan a la IA por cuestión
ANO_ACTUAL = time.localtime().tm_year
NOMBRES_CORTE = {"csj": "Corte Suprema de Justicia, Sala Laboral", "cc": "Corte Constitucional"}

_STOP = set("""
a al algo algun alguna algunas alguno algunos ante antes aquel aquella aquellas aquellos aqui asi aun aunque bajo bien
cada casi como con contra cual cuales cualquier cuando cuanto de del desde donde dos el ella ellas ello ellos en entre
era eran es esa esas ese eso esos esta estaba estado estan estar este esto estos fue fueron ha habia han hasta hay la
las le les lo los mas me mi mientras mismo mucho muy nada ni no nos nuestra nuestro o otra otras otro otros para pero
poco por porque que quien quienes se sea segun ser si sido sin sobre solo su sus tal tambien tan tanto te tiene tienen
todo todos tras tu un una unas uno unos usted ya yo dicho dicha dichos dichas cuya cuyo debe deben puede pueden hace
hizo tuvo tenia caso senor senora senores cliente mi mis quiero quiere solicita solicito pide pidio afirma indica
manifiesta ahora luego despues durante anos ano meses mes dias dia vez veces parte partes pagando dejados
""".split())


def _plano(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")


def palabras_clave(texto: str, maximo: int = 14, min_df: int = 1, max_frac: float = 0.6, min_tf: int = 1) -> list[str]:
    """Términos del caso más distintivos frente a la colección (tf-idf). Con min_df alto se
    prefieren términos jurídicos (presentes en muchas sentencias) a los hechos particulares."""
    tokens = [t for t in re.findall(r"[a-zñ]{4,}", _plano(texto)) if t not in _STOP]
    if not tokens:
        return []
    tf: dict[str, int] = {}
    for t in tokens:
        tf[t] = tf.get(t, 0) + 1
    df = busqueda.frecuencias(list(tf))
    n = busqueda.total_sentencias()
    puntajes = {}
    for t, f in tf.items():
        d = df.get(t, 0)
        if d < max(1, min_df) or d > max_frac * n or f < min_tf:
            continue
        puntajes[t] = (1 + math.log(f)) * math.log(n / d)
    return sorted(puntajes, key=puntajes.get, reverse=True)[:maximo]


def factor_reciente(ano: int | None) -> float:
    """1 para este año, 0,5 a los 10 años, 0,25 a los 20."""
    if not ano:
        return 0.5
    return 0.5 ** (max(0, ANO_ACTUAL - ano) / 10)


# ---------- Utilidades de ejecución ----------

class _Uso:
    def __init__(self) -> None:
        self.entrada = 0
        self.salida = 0
        self._lock = threading.Lock()

    def sumar(self, uso: dict) -> None:
        with self._lock:
            self.entrada += uso.get("entrada", 0)
            self.salida += uso.get("salida", 0)


def _avance(aid: int, paso: str, progreso: int, uso: _Uso | None = None) -> None:
    campos = {"paso": paso, "progreso": progreso}
    if uso:
        campos.update(tokens_entrada=uso.entrada, tokens_salida=uso.salida)
    casos.actualizar_analisis(aid, **campos)


def _base_resultado(f: dict) -> dict:
    return {k: f.get(k) for k in ("corte", "corte_clave", "sala", "tipo", "radicado", "ano", "fecha", "ponente",
                                  "tema", "subtema", "radicacion")}


def _excluidas(caso_id: int) -> set[int]:
    ids = set()
    for corte, radicado in casos.descartadas(caso_id):
        pid = busqueda.id_por_radicado(corte, radicado)
        if pid:
            ids.add(pid)
    return ids


def _cortes(caso: dict) -> list[str]:
    return caso.get("cortes") or ["csj", "cc"]


def _lista_por_corte(consultas: list[str], corte: str, caso: dict, excluir: set[int],
                     fallidas: set[str] | None = None) -> list[int]:
    """Fusiona varias consultas en una sola lista ordenada para una corte."""
    puntaje: dict[int, float] = {}
    for c in consultas:
        fts = busqueda.a_consulta_fts(c)
        if not fts:
            if fallidas is not None:
                fallidas.add(c)
            continue
        try:
            ids = busqueda.candidatos(fts, [corte], caso.get("desde"), caso.get("hasta"), POR_CONSULTA)
        except Exception:  # consulta inválida para FTS: se omite, pero queda registrada
            if fallidas is not None:
                fallidas.add(c)
            continue
        for pos, pid in enumerate(ids):
            if pid not in excluir:
                puntaje[pid] = puntaje.get(pid, 0) + 1 / (60 + pos)
    if caso.get("recientes", 1):
        anos = busqueda.anos(list(puntaje))
        for pid in puntaje:
            puntaje[pid] *= 0.55 + 0.45 * factor_reciente(anos.get(pid))
    return sorted(puntaje, key=puntaje.get, reverse=True)


def reunir_candidatas(grupos: dict[str, list[str]], caso: dict, limite: int,
                      fallidas: set[str] | None = None) -> tuple[list[int], dict[int, list[str]]]:
    """grupos: {cuestión: [consultas]}. Reparte cupos por cuestión y por corte
    (ronda por turnos) y devuelve (ids, cuestiones que recuperaron cada id)."""
    excluir = _excluidas(caso["id"])
    listas = {(g, corte): _lista_por_corte(consultas, corte, caso, excluir, fallidas)
              for g, consultas in grupos.items() for corte in _cortes(caso)}
    elegidas: list[int] = []
    origen: dict[int, list[str]] = {}
    posicion = 0
    while len(elegidas) < limite and any(posicion < len(l) for l in listas.values()):
        for (g, _), lista in listas.items():
            if posicion < len(lista):
                pid = lista[posicion]
                if pid not in origen:
                    if len(elegidas) >= limite:
                        continue
                    elegidas.append(pid)
                    origen[pid] = []
                if g not in origen[pid]:
                    origen[pid].append(g)
        posicion += 1
    # Una sentencia recuperada por varias cuestiones se anota en todas.
    for (g, _), lista in listas.items():
        for pid in lista[:POR_CONSULTA]:
            if pid in origen and g not in origen[pid]:
                origen[pid].append(g)
    return elegidas, origen


# ---------- Modo sin IA ----------

def analizar_local(aid: int, caso: dict, amplitud: str) -> None:
    _avance(aid, "Buscando palabras clave del caso", 10)
    texto = f"{caso['titulo']} {caso['descripcion']} {caso.get('pretensiones', '')}"
    claves = palabras_clave(texto)
    if not claves:
        raise ia.ErrorIA("Describe el caso con más detalle: no se encontraron palabras para buscar.")
    consultas = [" O ".join(claves), " ".join(claves[:4])]
    casos.actualizar_analisis(aid, planteamiento={
        "version": VERSION, "terminos_clave": claves,
        "consultas": [{"consulta": consultas[0], "proposito": "palabras más distintivas del caso"}]})
    _avance(aid, "Buscando sentencias", 40)
    ids, _ = reunir_candidatas({"general": consultas}, caso, CANDIDATAS[amplitud] // 2)
    resultados = []
    total = len(ids)
    for pos, pid in enumerate(ids):
        f = busqueda.ficha(pid)
        texto_s = busqueda.leer_texto(pid)
        plano = _plano(texto_s)
        presentes = [c for c in claves if c in plano]
        resultados.append({
            **_base_resultado(f),
            "puntaje": round(100 * (1 - pos / max(total, 1))),
            "por_que": "Coincide en: " + ", ".join(presentes[:10]),
            "fragmento": busqueda.fragmento(texto_s, claves[:6], 360),
        })
    casos.actualizar_analisis(aid, resultados=resultados, estado="listo", paso="Listo", progreso=100)


# ---------- Prompts con IA ----------

SISTEMA = (
    "Eres un abogado colombiano experto en derecho laboral, seguridad social y derecho constitucional, y conoces la "
    "jurisprudencia de la Corte Suprema de Justicia (Sala de Casación Laboral y Sala de Descongestión Laboral) y de "
    "la Corte Constitucional. Eres riguroso: no atribuyes a una sentencia lo que no dice. Respondes únicamente con "
    "un objeto JSON válido, en español."
)


def _texto_caso(caso: dict) -> str:
    partes = [f"Título: {caso['titulo']}", f"Hechos y particularidades:\n{caso['descripcion'].strip()}"]
    if caso.get("pretensiones", "").strip():
        partes.append(f"Lo que se pide o se discute:\n{caso['pretensiones'].strip()}")
    partes.append(f"Parte representada: {casos.POSICIONES.get(caso.get('posicion') or 'neutral')}")
    return "\n\n".join(partes)


def _prompt_planteamiento(caso: dict) -> str:
    return f"""Analiza este caso y prepara la búsqueda de precedentes.

{_texto_caso(caso)}

Devuelve este JSON:
{{
  "problema_juridico": "la pregunta jurídica central, en una o dos frases",
  "hechos_relevantes": ["3 a 8 hechos determinantes, concretos, sin nombres propios"],
  "hechos_por_precisar": ["0 a 5 datos que faltan en la descripción y pueden cambiar el análisis (p. ej., régimen del trabajador, fechas exactas)"],
  "cuestiones": [
    {{"id": "C1", "cuestion": "una pregunta jurídica concreta que el juez debe resolver en este caso",
      "por_que": "qué hechos del caso la hacen relevante",
      "consultas": [{{"consulta": "...", "proposito": "..."}}]}}
  ],
  "terminos_clave": ["10 a 20 expresiones jurídicas que usaría una sentencia análoga"]
}}

Sobre "cuestiones" (2 a 6, de la más determinante a la menos):
- Incluye las previas o procesales que pueden decidir el caso (prescripción o caducidad, procedencia, legitimación, competencia, carga de la prueba) y las de fondo.
- Si hay hechos cuya calificación jurídica es discutible (p. ej., si una comunicación ya era un despido), plantéalo como cuestión.

Sobre "consultas" (2 a 4 por cuestión), que se corren en un buscador de texto completo:
- Todas las palabras sueltas deben aparecer; "frase exacta" entre comillas; O entre alternativas; prefijo con * (p. ej., reintegr*).
- 2 a 5 elementos por consulta, con las expresiones técnicas como las redactan las cortes (la Sala Laboral y la Corte Constitucional usan vocabularios distintos: cubre ambos).
- Una consulta estrecha (hechos particulares) y una amplia (la regla). Sin nombres, ciudades ni fechas."""


def _texto_ficha(ref: str, f: dict, ficha: dict) -> str:
    r = ficha["resultado"]
    lineas = [f"[{ref}] {NOMBRES_CORTE.get(f['corte_clave'], f['corte'])} · {f.get('sala') or ''} · "
              f"{f.get('tipo') or ''} {f['radicado']} ({f.get('ano')})"]
    if ficha["hechos"]:
        lineas.append("Hechos: " + " | ".join(ficha["hechos"]))
    if ficha["problema_juridico"]:
        lineas.append(f"Problema jurídico: {ficha['problema_juridico']}")
    lineas.append(f"Resultado: {r['tipo']} — {r['efecto']} (favoreció a: {r['favorece_a']})")
    if not ficha["decide_fondo"]:
        lineas.append(f"NO decide el fondo: {ficha['motivo_si_no_decide_fondo']}")
    for n, regla in enumerate(ficha["reglas"], 1):
        marca = "cita verificada" if regla["verificada"] else "cita NO verificada"
        lineas.append(f"Regla {n} ({regla['papel']}; {marca}): {regla['regla']}")
    return "\n".join(lineas)


def _prompt_comparacion(caso: dict, plan: dict, bloques: list[str]) -> str:
    hechos = "\n".join(f"H{i}. {h}" for i, h in enumerate(plan["hechos_relevantes"], 1))
    cuestiones = "\n".join(f"{c['id']}. {c['cuestion']}" for c in plan["cuestiones"])
    return f"""CASO
{_texto_caso(caso)}

Hechos determinantes del caso:
{hechos}

Cuestiones del caso:
{cuestiones}

FICHAS DE SENTENCIAS (las elaboró un relator sin conocer el caso; NO las modifiques)
{chr(10).join(bloques)}

Compara cada sentencia con el caso. Devuelve este JSON, con una entrada por cada ficha:
{{"comparaciones": [{{
  "ref": "S1",
  "cuestiones": ["C1"],
  "hechos": [{{"h": "H1", "relacion": "coincide | difiere | no_consta", "detalle": "máximo 20 palabras"}}],
  "analogias": "hechos de la sentencia especialmente parecidos al caso que conviene destacar, aunque no estén en la lista (máximo 40 palabras; vacío si no hay)",
  "diferencias": "diferencias que pueden impedir aplicarla (máximo 40 palabras)",
  "utilidad": "a_favor | en_contra | mixta | ninguna",
  "explicacion_utilidad": "por qué, a partir del resultado y de las reglas de la ficha (máximo 45 palabras)",
  "pertinencia": 0
}}]}}

Reglas:
- Evalúa TODOS los hechos determinantes (H1, H2…) en cada sentencia.
- No cambies el resultado ni las reglas de la ficha. Si la ficha dice que se negó, no digas que se concedió.
- "cuestiones": solo las cuestiones del caso que la sentencia DECIDE con una regla de papel "ratio"; no las que solo menciona. Lista vacía si ninguna.
- "utilidad" es para la parte representada. Si la posición es neutral, usa "mixta" o "ninguna" y explica a quién sirve. Una sentencia con hechos análogos que favoreció a la contraparte suele ser "en_contra", salvo que su regla, aplicada a los hechos del caso, lleve a lo contrario; explícalo.
- Si la sentencia no decide el fondo, pertinencia máxima 40, salvo que su motivo sea en sí una cuestión del caso.
- "pertinencia": 80-100 hechos análogos y ratio sobre una cuestión del caso; 60-79 ratio sobre una cuestión con hechos distintos; 40-59 solo reitera la regla o es referencia útil; menos de 40 no sirve. Una regla de papel "reiteracion" u "obiter" no justifica más de 59."""


def _prompt_cuestion(caso: dict, plan: dict, cuestion: dict, precedentes: list[dict]) -> str:
    bloques = []
    for p in precedentes:
        fi, comp = p["ficha"], p["comparacion"]
        reglas = "\n".join(
            f"   - ({r['papel']}{'' if r['verificada'] else ', cita no verificada'}) {r['regla']}"
            + (f"\n     Texto: «{r['cita'][:400]}»" if r["verificada"] and r["cita"] else "")
            for r in fi["reglas"])
        bloques.append(
            f"[{p['radicado']}] {NOMBRES_CORTE.get(p['corte_clave'])}, {p.get('sala') or ''}, {p.get('ano')}. "
            f"Resultado: {fi['resultado']['efecto']} (favoreció a: {fi['resultado']['favorece_a']})."
            f"{'' if fi['decide_fondo'] else ' NO decidió el fondo: ' + fi['motivo_si_no_decide_fondo']}\n"
            f"   Reglas:\n{reglas}\n"
            f"   Frente al caso: {comp.get('analogias') or ''} Diferencias: {comp.get('diferencias') or '—'} "
            f"Utilidad: {comp.get('utilidad')} — {comp.get('explicacion_utilidad') or ''}")
    recientes = ("- Funda los argumentos preferiblemente en las sentencias más recientes. Si solo hay sentencias antiguas "
                 "(más de 10 años), adviértelo; si una más reciente dice algo distinto que una antigua, señala que la "
                 "reciente refleja la postura actual.\n") if caso.get("recientes", 1) else ""
    neutral = (caso.get("posicion") or "neutral") == "neutral"
    return f"""CASO
{_texto_caso(caso)}

Hechos determinantes: {' | '.join(plan['hechos_relevantes'])}

CUESTIÓN {cuestion['id']}: {cuestion['cuestion']}
Por qué importa: {cuestion.get('por_que') or '—'}

PRECEDENTES SOBRE ESTA CUESTIÓN (son los únicos que puedes citar):
{chr(10).join(bloques) if bloques else '(ninguno en la base)'}

Devuelve este JSON:
{{
  "estado": "qué han decidido estos precedentes sobre la cuestión, 60 a 160 palabras. Solo reporta lo que dicen sus reglas y resultados; cada afirmación con su radicado entre corchetes, p. ej. [SL1234-2020]. Distingue posturas distintas.",
  "argumentos": [{{"tesis": "el argumento en una frase", "desarrollo": "cómo construirlo con los hechos del caso (máximo 90 palabras)", "apoyo": ["radicados de la lista"], "objecion": "la objeción previsible y cómo responderla (máximo 60 palabras)"}}],
  "contraparte": [{{"tesis": "argumento previsible de la otra parte", "apoyo": ["radicados de la lista"]}}],
  "por_verificar": ["hechos, pruebas o cálculos (p. ej., términos con las fechas del expediente) de los que depende la cuestión"],
  "vacios": "qué no cubren estos precedentes; vacío si nada"
}}

Reglas:
- {"La posición es neutral: en 'argumentos' presenta los de la parte trabajadora y en 'contraparte' los de la empleadora." if neutral else "Los 'argumentos' (1 a 4) deben favorecer a la parte representada."}
- Antes de proponer un argumento, comprueba que su conclusión no perjudica la pretensión o la defensa de esa parte, ni contradice otro argumento. Si una lectura de los hechos ayuda en esta cuestión pero perjudica en otra, dilo en "objecion".
- Cita solo radicados de la lista y solo para lo que dicen sus reglas o resultados. No atribuyas a una sentencia una regla que no aparece en su ficha. Una regla de papel "reiteracion" se cita como reiteración, no como lo decidido.
- Si ningún precedente apoya un argumento, deja "apoyo" vacío y escribe en el desarrollo "(sin precedente en la base)".
- No hagas cómputos de términos ni des por probado lo que no está en la descripción del caso: ponlo en "por_verificar".
{recientes}- Si no hay precedentes, "estado" debe decir "No se encontraron precedentes sobre esta cuestión en la base"."""


def _prompt_revision_tema(caso: dict, c: dict, reglas_por_rad: dict[str, list[str]]) -> str:
    a = c.get("analisis") or {}
    args = "\n".join(f"A{i}. {x['tesis']} — {x.get('desarrollo', '')} Apoyo: {', '.join(x['apoyo']) or 'ninguno'}"
                     for i, x in enumerate(a.get("argumentos") or [], 1))
    citados = {rad for x in a.get("argumentos") or [] for rad in x["apoyo"]}
    reglas = "\n".join(f"[{rad}] " + " / ".join(r) for rad, r in reglas_por_rad.items() if rad in citados)
    return f"""Revisa, como abogado litigante experimentado, los argumentos preparados para UNA cuestión de este caso.

{_texto_caso(caso)}

CUESTIÓN {c['id']}: {c['cuestion']}
ARGUMENTOS
{args or '(sin argumentos)'}

LO QUE REALMENTE DICEN LOS PRECEDENTES CITADOS (reglas y resultado de sus fichas)
{reglas or '(ninguno)'}

Busca solo problemas reales en cada argumento:
(a) "contradiccion": su conclusión perjudica a la parte representada o choca con otro argumento de esta cuestión;
(b) "cita_indebida": atribuye a un precedente algo que sus reglas o su resultado no dicen;
(c) "hecho_no_probado": da por probado algo que no está en los hechos del caso.

Devuelve este JSON (lista vacía si no hay problemas):
{{"revision": [{{"argumento": 1, "tipo": "contradiccion | cita_indebida | hecho_no_probado", "problema": "explicación breve", "gravedad": "alta | media | baja"}}]}}"""


def _prompt_coherencia(caso: dict, cuestiones: list[dict]) -> str:
    tesis = "\n".join(f"{c['id']}-A{i}. {x['tesis']}" for c in cuestiones
                      for i, x in enumerate((c.get("analisis") or {}).get("argumentos") or [], 1))
    return f"""Estas son las tesis que se proponen para defender a una parte en este caso, agrupadas por cuestión.

{_texto_caso(caso)}

TESIS
{tesis or '(ninguna)'}

Revisa la coherencia de la estrategia EN CONJUNTO: ¿alguna tesis, si se acepta, hace caer la pretensión o la defensa de la parte representada en otra cuestión? (Por ejemplo: sostener que una comunicación no fue el despido puede ayudar con la prescripción pero hacer que no haya despido sin permiso.)

Devuelve este JSON:
{{"contradicciones": [{{"tesis": "C1-A1", "choca_con": "C2-A1", "problema": "explicación breve", "gravedad": "alta | media | baja"}}],
  "observaciones_generales": ["0 a 3 observaciones sobre la estrategia del caso en conjunto"]}}
Si no hay contradicciones, "contradicciones" es una lista vacía."""


# ---------- Validaciones deterministas ----------

_RE_CITA = re.compile(r"\[([^\[\]]{3,40})\]")
# Radicados: T-760-08, T-760/08, SU-214/16, C-355-06 (Corte Constitucional);
# SL1234-2020, STL123-2021, AL45-2019 o 39601(21-02-12) (Corte Suprema).
_RE_RADICADO = re.compile(r"^(?:(?:T|C|SU|A)-\d{1,4}[-/]\d{2,4}|S?[A-Z]{1,3}\d{1,6}-\d{4}|\d{5,6}(?:\(\d{2}-\d{2}-\d{2}\))?)$")


def _marcar_citas(texto: str, permitidos: set[str]) -> tuple[str, list[str]]:
    """Marca las citas [RADICADO] que no están entre los precedentes revisados."""
    ajenas = []

    def reemplazo(m):
        rad = m.group(1).strip()
        if rad in permitidos or not _RE_RADICADO.match(rad):
            return m.group(0)
        ajenas.append(rad)
        return f"[{rad} — no está entre los precedentes revisados para este tema: verifíquela]"

    return _RE_CITA.sub(reemplazo, texto or ""), ajenas


def _similitud(comparacion: list[dict], n_hechos: int) -> int:
    if not n_hechos:
        return 0
    coinciden = sum(1 for h in comparacion if h.get("relacion") == "coincide")
    difieren = sum(1 for h in comparacion if h.get("relacion") == "difiere")
    return max(0, min(10, round(10 * (coinciden - 0.25 * difieren) / n_hechos)))


# ---------- Análisis con IA ----------

def _falla(errores: list[str], que: str, exc: Exception) -> None:
    """Mensaje neutro para la persona; el detalle técnico va a datos/registro_ia.log."""
    ia.registrar(f"{que}: {exc}")
    if getattr(exc, "accionable", False):
        errores.append(str(exc))
    else:
        errores.append(f"No se pudo completar {que}. Intente de nuevo.")


def _llamar(prompt: str, uso: _Uso, max_tokens: int) -> dict:
    datos, u = ia.chat_json([{"role": "system", "content": SISTEMA}, {"role": "user", "content": prompt}],
                            max_tokens=max_tokens)
    uso.sumar(u)
    return datos


def _normalizar_plan(plan: dict, caso: dict) -> dict:
    cuestiones = []
    for i, c in enumerate(plan.get("cuestiones") or [], 1):
        if not isinstance(c, dict) or not c.get("cuestion"):
            continue
        consultas = []
        for q in (c.get("consultas") or [])[:4]:
            if isinstance(q, dict) and q.get("consulta"):
                consultas.append({"consulta": str(q["consulta"]), "proposito": str(q.get("proposito") or "")})
            elif isinstance(q, str) and q.strip():
                consultas.append({"consulta": q, "proposito": ""})
        cuestiones.append({"id": f"C{len(cuestiones) + 1}", "cuestion": str(c["cuestion"])[:400],
                           "por_que": str(c.get("por_que") or "")[:400], "consultas": consultas})
    if not cuestiones:
        raise ia.ErrorIA("La IA no identificó cuestiones jurídicas. Describe el caso con más detalle e intenta de nuevo.")
    return {
        "version": VERSION,
        "posicion": caso.get("posicion") or "neutral",
        "problema_juridico": str(plan.get("problema_juridico") or "")[:600],
        "hechos_relevantes": [str(h)[:300] for h in plan.get("hechos_relevantes") or []][:8],
        "hechos_por_precisar": [str(h)[:300] for h in plan.get("hechos_por_precisar") or []][:5],
        "cuestiones": cuestiones[:6],
        "terminos_clave": [str(t) for t in plan.get("terminos_clave") or []][:20],
    }


def analizar_ia(aid: int, caso: dict, amplitud: str) -> None:
    uso = _Uso()
    _avance(aid, "La IA está identificando el problema jurídico y los temas a resolver", 4)
    plan = _normalizar_plan(_llamar(_prompt_planteamiento(caso), uso, 3500), caso)
    texto_caso = f"{caso['titulo']} {caso['descripcion']} {caso.get('pretensiones', '')}"
    claves = palabras_clave(texto_caso, 12)
    grupos = {c["id"]: [q["consulta"] for q in c["consultas"]] for c in plan["cuestiones"]}
    if claves:  # red de seguridad con las palabras más distintivas del caso
        grupos["general"] = [" O ".join(claves)]
    plan["consultas"] = [{"consulta": q["consulta"], "proposito": f"{c['id']}: {q['proposito']}"}
                         for c in plan["cuestiones"] for q in c["consultas"]]
    if claves:
        plan["consultas"].append({"consulta": grupos["general"][0], "proposito": "palabras más distintivas del caso"})
    casos.actualizar_analisis(aid, planteamiento=plan)

    _avance(aid, "Buscando sentencias candidatas en cada corte", 10, uso)
    fallidas: set[str] = set()
    ids, origen = reunir_candidatas(grupos, caso, CANDIDATAS[amplitud], fallidas)
    if fallidas:
        plan["consultas_fallidas"] = sorted(fallidas)
        casos.actualizar_analisis(aid, planteamiento=plan)
    if not ids:
        casos.actualizar_analisis(aid, resultados=[], estado="listo", paso="Listo", progreso=100,
                                  tokens_entrada=uso.entrada, tokens_salida=uso.salida)
        return

    def avance_fichas(hechas, total):
        _avance(aid, f"La IA está leyendo las sentencias sin conocer el caso ({hechas} de {total})",
                12 + int(46 * hechas / total), uso)

    fichas_por_id, errores_fichas = fichas.elaborar_varias(ids, uso.sumar, avance_fichas)
    if not fichas_por_id:
        raise ia.ErrorIA(errores_fichas[0] if errores_fichas else "No se pudo leer ninguna sentencia.")
    errores: list[str] = []
    if errores_fichas:
        ia.registrar("Fichas: " + " | ".join(errores_fichas[:5]))
        errores.append(f"No se pudieron leer {len(errores_fichas)} de las sentencias candidatas; el análisis sigue con las demás.")
    ids = [pid for pid in ids if pid in fichas_por_id]
    datos = {pid: busqueda.ficha(pid) for pid in ids}

    # Comparación con el caso, por lotes.
    refs = {f"S{n}": pid for n, pid in enumerate(ids, 1)}
    lotes = [list(refs.items())[i : i + LOTE_COMPARACION] for i in range(0, len(refs), LOTE_COMPARACION)]
    comparaciones: dict[int, dict] = {}
    hechos_lotes = 0

    def comparar(lote, intento=1):
        bloques = [_texto_ficha(ref, datos[pid], fichas_por_id[pid]) for ref, pid in lote]
        respuesta = _llamar(_prompt_comparacion(caso, plan, bloques), uso, 750 * len(lote) + 600)
        completas = [c for c in respuesta.get("comparaciones") or []
                     if isinstance(c, dict) and "pertinencia" in c and "utilidad" in c and c.get("ref")]
        hechas = {str(c["ref"]).strip("[] ") for c in completas}
        faltan = [(ref, pid) for ref, pid in lote if ref not in hechas]
        if faltan and intento == 1:  # respuesta cortada o incompleta: se piden las que faltan
            _, extra = comparar(faltan, 2)
            completas += extra
        return lote, completas

    _avance(aid, f"Comparando {len(ids)} sentencias con los hechos del caso", 60, uso)
    with ThreadPoolExecutor(max_workers=HILOS) as grupo:
        for futuro in as_completed([grupo.submit(comparar, lote) for lote in lotes]):
            try:
                lote, lista = futuro.result()
            except ia.ErrorIA as exc:
                _falla(errores, "la comparación de algunas sentencias con el caso", exc)
                continue
            validos = dict(lote)
            for comp in lista:
                if isinstance(comp, dict) and str(comp.get("ref", "")).strip("[] ") in validos:
                    comparaciones[validos[str(comp["ref"]).strip("[] ")]] = comp
            hechos_lotes += 1
            _avance(aid, f"Comparando con los hechos del caso ({min(hechos_lotes * LOTE_COMPARACION, len(ids))} de {len(ids)})",
                    60 + int(18 * hechos_lotes / len(lotes)), uso)

    ids_cuestiones = {c["id"] for c in plan["cuestiones"]}
    n_hechos = len(plan["hechos_relevantes"])
    resultados = []
    for pid in ids:
        comp = comparaciones.get(pid)
        if not comp:
            continue
        ficha = fichas_por_id[pid]
        try:
            pertinencia = max(0, min(100, int(float(comp.get("pertinencia", 0)))))
        except (TypeError, ValueError):
            pertinencia = 0
        if not ficha["decide_fondo"]:
            pertinencia = min(pertinencia, 40) if not comp.get("cuestiones") else pertinencia
        if not any(r["papel"] == "ratio" for r in ficha["reglas"]):
            pertinencia = min(pertinencia, 59)
        hechos_comp = [h for h in comp.get("hechos") or [] if isinstance(h, dict)]
        utilidad = comp.get("utilidad") if comp.get("utilidad") in ("a_favor", "en_contra", "mixta", "ninguna") else "ninguna"
        f = datos[pid]
        bono = round(8 * factor_reciente(f.get("ano"))) if caso.get("recientes", 1) else 0
        resultados.append({
            **_base_resultado(f),
            "cuestiones": [c for c in comp.get("cuestiones") or [] if c in ids_cuestiones],
            "recuperada_por": origen.get(pid, []),
            "ficha": ficha,
            "comparacion": {
                "hechos": [{"h": str(h.get("h")), "relacion": h.get("relacion") if h.get("relacion") in ("coincide", "difiere", "no_consta") else "no_consta",
                            "detalle": str(h.get("detalle") or "")[:200]} for h in hechos_comp],
                "analogias": str(comp.get("analogias") or "")[:400],
                "diferencias": str(comp.get("diferencias") or "")[:400],
                "utilidad": utilidad,
                "explicacion_utilidad": str(comp.get("explicacion_utilidad") or "")[:400],
            },
            "similitud_hechos": _similitud(hechos_comp, n_hechos),
            "pertinencia": pertinencia,
            "puntaje": min(100, pertinencia + bono),
        })
    resultados.sort(key=lambda r: (-r["puntaje"], -r["similitud_hechos"], -(r.get("ano") or 0)))

    # Análisis por cuestión.
    _avance(aid, "La IA está desarrollando cada tema jurídico", 80, uso)
    def analizar_cuestion(c):
        propios = [r for r in resultados if c["id"] in r["cuestiones"] and r["pertinencia"] >= UMBRAL_PRECEDENTE]
        if caso.get("recientes", 1):
            propios.sort(key=lambda r: (-r["puntaje"], -(r.get("ano") or 0)))
        propios = propios[:MAX_POR_CUESTION]
        a = _llamar(_prompt_cuestion(caso, plan, c, propios), uso, 4000)
        permitidos = {r["radicado"] for r in propios}
        ajenas: list[str] = []
        estado, x = _marcar_citas(str(a.get("estado") or ""), permitidos)
        ajenas += x

        def limpiar_args(lista, con_detalle):
            salida = []
            for arg in lista or []:
                if not isinstance(arg, dict) or not arg.get("tesis"):
                    continue
                apoyo = [str(r).strip("[] ") for r in arg.get("apoyo") or []]
                fuera = [r for r in apoyo if r not in permitidos]
                ajenas.extend(fuera)
                item = {"tesis": str(arg["tesis"])[:400], "apoyo": [r for r in apoyo if r in permitidos],
                        "apoyo_no_verificado": fuera}
                if con_detalle:
                    desarrollo, y = _marcar_citas(str(arg.get("desarrollo") or "")[:900], permitidos)
                    objecion, z = _marcar_citas(str(arg.get("objecion") or "")[:600], permitidos)
                    ajenas.extend(y + z)
                    item.update(desarrollo=desarrollo, objecion=objecion)
                salida.append(item)
            return salida

        c["analisis"] = {
            "incompleto": bool(a.get("_reparado")),
            "estado": estado,
            "argumentos": limpiar_args(a.get("argumentos"), True)[:4],
            "contraparte": limpiar_args(a.get("contraparte"), False)[:3],
            "por_verificar": [str(v)[:300] for v in a.get("por_verificar") or []][:6],
            "vacios": str(a.get("vacios") or "")[:500],
            "citas_ajenas": sorted(set(ajenas)),
        }
        c["precedentes"] = [r["radicado"] for r in propios]
        return c

    with ThreadPoolExecutor(max_workers=HILOS) as grupo:
        futuros = [grupo.submit(analizar_cuestion, c) for c in plan["cuestiones"]]
        for futuro in as_completed(futuros):
            try:
                futuro.result()
            except ia.ErrorIA as exc:
                _falla(errores, "el análisis de uno de los temas", exc)
    for c in plan["cuestiones"]:
        c.setdefault("analisis", {"estado": "No se pudo desarrollar esta cuestión. Vuelva a buscar precedentes para completarla.",
                                  "argumentos": [], "contraparte": [], "por_verificar": [], "vacios": "", "citas_ajenas": []})
        c.setdefault("precedentes", [])

    # Revisión crítica: una llamada por tema (respuestas cortas) y una de coherencia global.
    _avance(aid, "Revisión crítica de los argumentos", 92, uso)
    citados = {rad for c in plan["cuestiones"] for a in c["analisis"]["argumentos"] for rad in a["apoyo"]}
    reglas_por_rad = {r["radicado"]: [f"({x['papel']}) {x['regla']}" for x in r["ficha"]["reglas"]] + [f"Resultado: {r['ficha']['resultado']['efecto']}"]
                      for r in resultados if r["radicado"] in citados}

    def anotar(c, idx, tipo, problema, gravedad):
        if 0 <= idx < len(c["analisis"]["argumentos"]):
            c["analisis"]["argumentos"][idx].setdefault("revision", []).append({
                "tipo": str(tipo or ""), "problema": str(problema or "")[:500],
                "gravedad": gravedad if gravedad in ("alta", "media", "baja") else "media"})

    def revisar_tema(c):
        if not c["analisis"]["argumentos"]:
            return c, {}
        return c, _llamar(_prompt_revision_tema(caso, c, reglas_por_rad), uso, 2000)

    with ThreadPoolExecutor(max_workers=HILOS) as grupo:
        futuros = {grupo.submit(revisar_tema, c): c for c in plan["cuestiones"]}
        futuro_global = grupo.submit(_llamar, _prompt_coherencia(caso, plan["cuestiones"]), uso, 1500)
        for futuro in as_completed(futuros):
            c = futuros[futuro]
            try:
                _, revision = futuro.result()
            except ia.ErrorIA as exc:
                _falla(errores, f"la revisión crítica del tema {c['id']}", exc)
                continue
            for obs in revision.get("revision") or []:
                if isinstance(obs, dict):
                    try:
                        anotar(c, int(obs.get("argumento")) - 1, obs.get("tipo"), obs.get("problema"), obs.get("gravedad"))
                    except (TypeError, ValueError):
                        continue
        try:
            coherencia = futuro_global.result()
            for obs in coherencia.get("contradicciones") or []:
                if not isinstance(obs, dict):
                    continue
                m = re.match(r"(C\d+)-A(\d+)", str(obs.get("tesis") or ""))
                c = next((x for x in plan["cuestiones"] if m and x["id"] == m.group(1)), None)
                if c:
                    con = f" (choca con {obs.get('choca_con')})" if obs.get("choca_con") else ""
                    anotar(c, int(m.group(2)) - 1, "contradiccion", f"{obs.get('problema') or ''}{con}", obs.get("gravedad"))
            plan["observaciones_generales"] = [str(x)[:500] for x in coherencia.get("observaciones_generales") or []][:3]
        except ia.ErrorIA as exc:
            _falla(errores, "la revisión de coherencia de la estrategia", exc)

    if errores:
        plan["errores"] = list(dict.fromkeys(errores))[:4]
    casos.actualizar_analisis(aid, planteamiento=plan, resultados=resultados, estado="listo", paso="Listo",
                              progreso=100, tokens_entrada=uso.entrada, tokens_salida=uso.salida)


def iniciar(caso_id: int, usuario_id: int | None, amplitud: str = "normal") -> int:
    caso = casos.obtener_caso(caso_id)
    if not caso:
        raise KeyError(caso_id)
    if len(caso["descripcion"].strip()) < 40:
        raise ValueError("Describe los hechos del caso con más detalle (al menos un par de frases).")
    amplitud = amplitud if amplitud in CANDIDATAS else "normal"
    estado_ia = ia.estado()
    modo = "ia" if estado_ia["activa"] else "local"
    aid = casos.crear_analisis(caso_id, usuario_id, modo, estado_ia["modelo"] if modo == "ia" else None)
    casos.registrar(caso_id, usuario_id, "Buscó precedentes", "con IA (DeepSeek)" if modo == "ia" else "sin IA (palabras clave)")
    casos.tocar_caso(caso_id)

    def trabajo():
        try:
            (analizar_ia if modo == "ia" else analizar_local)(aid, caso, amplitud)
        except ia.ErrorIA as exc:
            ia.registrar(f"Análisis {aid}: {exc}")
            mensaje = str(exc) if getattr(exc, "accionable", False) else (
                "No se pudo completar la búsqueda con IA. Intente de nuevo; si se repite, envíe el archivo "
                "datos/registro_ia.log de la carpeta del buscador.")
            casos.actualizar_analisis(aid, estado="error", error=mensaje, paso="Error")
        except Exception as exc:  # error inesperado: se guarda para mostrarlo
            traceback.print_exc()
            casos.actualizar_analisis(aid, estado="error", error=f"Error inesperado: {exc}", paso="Error")

    threading.Thread(target=trabajo, daemon=True, name=f"analisis-{aid}").start()
    return aid


def con_ids(analisis: dict) -> dict:
    """Agrega el id actual de cada sentencia (cambia al reconstruir la base)."""
    for r in analisis.get("resultados") or []:
        r["id"] = busqueda.id_por_radicado(r["corte_clave"], r["radicado"])
    return analisis
