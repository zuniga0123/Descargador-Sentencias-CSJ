"""Buscador de precedentes para un caso.

Con DeepSeek configurado:
  1. Planteamiento: la IA lee el caso y devuelve el problema jurídico, el
     asunto de fondo, los hechos determinantes y varias consultas de búsqueda.
  2. Candidatas: cada consulta se corre en la base local y se combinan los
     resultados (fusión por posición). Se descartan las que la persona ya
     marcó como "no sirve" en este caso.
  3. Extractos: de cada candidata se toman los antecedentes, los pasajes que
     más se parecen al caso y la decisión (unos 2.400 caracteres; nunca la
     sentencia completa).
  4. Evaluación: la IA califica cada candidata por similitud de hechos y por
     si resuelve el mismo asunto de fondo, y explica por qué.
  5. Síntesis: un párrafo con la posición de la jurisprudencia, con citas.

Sin IA se hace una versión local: palabras clave del caso -> búsqueda ->
orden por coincidencia, sin explicaciones.
"""

from __future__ import annotations

import math
import re
import threading
import traceback
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import busqueda, casos, ia
from .texto import marcar_secciones, reflujo_pdf

LOTE = 8                 # candidatas por llamada de evaluación
HILOS = 3                # llamadas simultáneas a DeepSeek
CANDIDATAS = {"normal": 40, "amplia": 80}
UMBRAL_PRECEDENTE = 40   # puntaje mínimo para mostrarla como precedente

_STOP = set("""
a al algo algun alguna algunas alguno algunos ante antes aquel aquella aquellas aquellos aqui asi aun aunque bajo bien
cada casi como con contra cual cuales cualquier cuando cuanto de del desde donde dos el ella ellas ello ellos en entre
era eran es esa esas ese eso esos esta estaba estado estan estar este esto estos fue fueron ha habia han hasta hay la
las le les lo los mas me mi mientras mismo mucho muy nada ni no nos nuestra nuestro o otra otras otro otros para pero
poco por porque que quien quienes se sea segun ser si sido sin sobre solo su sus tal tambien tan tanto te tiene tienen
todo todos tras tu un una unas uno unos usted ya yo dicho dicha dichos dichas cuya cuyo debe deben puede pueden hace
hizo tuvo tenia caso senor senora senores cliente mi mis quiero quiere solicita solicito pide pidio afirma indica
manifiesta ahora luego despues durante anos ano meses mes dias dia vez veces parte partes
""".split())


def _plano(texto: str) -> str:
    sin = "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")
    return sin


# ---------- Utilidades de texto ----------

def palabras_clave(texto: str, maximo: int = 14) -> list[str]:
    """Términos del caso más distintivos frente a la colección (tf-idf)."""
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
        if d == 0 or d > 0.6 * n:
            continue
        puntajes[t] = (1 + math.log(f)) * math.log(n / d)
    return sorted(puntajes, key=puntajes.get, reverse=True)[:maximo]


def _bloques(texto: str, corte_clave: str) -> list[str]:
    if corte_clave == "csj":
        texto = reflujo_pdf(texto)
    return [b.strip() for b in marcar_secciones(texto).split("\n\n") if b.strip()]


def _limpio(bloque: str) -> str:
    bloque = re.sub(r"[#*_>|`]+", " ", bloque)
    return re.sub(r"\s+", " ", bloque).strip()


def _tomar(bloques: list[str], desde: int, maximo: int) -> tuple[str, set[int]]:
    salida, usados = [], set()
    total = 0
    for i in range(desde, len(bloques)):
        if bloques[i].startswith("#"):
            if salida:
                break
            continue
        trozo = _limpio(bloques[i])
        salida.append(trozo)
        usados.add(i)
        total += len(trozo)
        if total >= maximo:
            break
    return " ".join(salida)[:maximo], usados


_RE_HECHOS = re.compile(r"ANTECEDENTES|HECHOS|LA DEMANDA|S[IÍ]NTESIS|ASUNTO", re.I)
_RE_DECISION = re.compile(r"RESUELVE|DECISI[OÓ]N|DECIDE|FALLA", re.I)


def extracto(pid: int, terminos: list[str]) -> dict:
    """Lo esencial de una sentencia para que la IA la compare con el caso."""
    texto = busqueda.leer_texto(pid)
    datos = busqueda.ficha(pid) or {}
    bloques = _bloques(texto, datos.get("corte_clave", ""))
    titulos = [(i, b) for i, b in enumerate(bloques) if b.startswith("#")]

    inicio_hechos = next((i + 1 for i, b in titulos if _RE_HECHOS.search(b)), min(3, len(bloques)))
    hechos, usados = _tomar(bloques, inicio_hechos, 900)

    decision = ""
    for i, b in reversed(titulos):
        if _RE_DECISION.search(b):
            decision, u = _tomar(bloques, i + 1, 600)
            usados |= u
            break
    if not decision:
        plano = _limpio(texto)
        m = list(re.finditer(r"RESUELVE|NO CASA|CASA LA SENTENCIA|DECIDE", plano))
        if m:
            decision = plano[m[-1].start() : m[-1].start() + 600]

    patron = [t for t in terminos if len(t) >= 4]
    puntuados = []
    for i, b in enumerate(bloques):
        if i in usados or b.startswith("#") or len(b) < 200:
            continue
        plano = _plano(b)
        coincide = sum(1 for t in patron if t in plano)
        if coincide:
            puntuados.append((coincide, i))
    puntuados.sort(reverse=True)
    pasajes = [busqueda.fragmento(_limpio(bloques[i]), patron, 480) for _, i in puntuados[:3]]

    return {
        "hechos": hechos,
        "pasajes": pasajes,
        "decision": decision,
        "resumen": (datos.get("resumen") or "")[:400],
    }


def _ficha_texto(ref: str, f: dict, e: dict) -> str:
    cabeza = f"[{ref}] {f['corte']} · {f.get('sala') or ''} · {f.get('tipo')} {f['radicado']} ({f.get('fecha') or f.get('ano')})"
    partes = [cabeza]
    if f.get("tema") and not str(f["tema"]).startswith("Otros"):
        partes.append(f"Tema: {f['tema']} / {f.get('subtema') or ''}")
    if e["resumen"]:
        partes.append(f"Síntesis de relatoría: {e['resumen']}")
    if e["hechos"]:
        partes.append(f"Antecedentes: {e['hechos']}")
    for p in e["pasajes"]:
        partes.append(f"Pasaje: {p}")
    if e["decision"]:
        partes.append(f"Decisión: {e['decision']}")
    return "\n".join(partes)


# ---------- Prompts ----------

SISTEMA = (
    "Eres un abogado colombiano experto en jurisprudencia laboral y constitucional "
    "(Corte Suprema de Justicia, Sala de Casación Laboral y Sala de Descongestión Laboral; "
    "Corte Constitucional). Respondes únicamente con un objeto JSON válido, en español."
)


def _texto_caso(caso: dict) -> str:
    partes = [f"Título: {caso['titulo']}", f"Hechos y particularidades:\n{caso['descripcion'].strip()}"]
    if caso.get("pretensiones", "").strip():
        partes.append(f"Lo que se pide o se discute:\n{caso['pretensiones'].strip()}")
    return "\n\n".join(partes)


def _prompt_planteamiento(caso: dict) -> str:
    return f"""Prepara la búsqueda de precedentes judiciales para este caso.

{_texto_caso(caso)}

Devuelve este JSON:
{{
  "problema_juridico": "la pregunta jurídica central, en una o dos frases",
  "asunto_de_fondo": "lo que un juez debe decidir de fondo",
  "hechos_relevantes": ["3 a 8 hechos determinantes, en abstracto, sin nombres propios"],
  "normas": ["normas probablemente aplicables"],
  "terminos_clave": ["10 a 20 palabras o expresiones jurídicas que usaría una sentencia análoga"],
  "consultas": [{{"consulta": "...", "proposito": "qué busca esta consulta"}}]
}}

Reglas para "consultas" (5 a 8), que se correrán en un buscador de texto completo:
- Todas las palabras sueltas deben aparecer en la sentencia; "frase exacta" entre comillas; O entre alternativas (p. ej. "fuero de maternidad" O "estado de embarazo"); prefijo con * (p. ej. reintegr*).
- Cada consulta con 2 a 5 elementos. Usa las expresiones técnicas como las redactan las cortes.
- Mezcla consultas estrechas (hechos muy particulares del caso) y amplias (el asunto de fondo).
- Sin nombres de personas, empresas, ciudades ni fechas."""


def _prompt_evaluacion(caso: dict, plan: dict, fichas: list[str]) -> str:
    hechos = "\n".join(f"- {h}" for h in plan.get("hechos_relevantes") or [])
    return f"""CASO
{_texto_caso(caso)}

Problema jurídico: {plan.get('problema_juridico') or '-'}
Asunto de fondo: {plan.get('asunto_de_fondo') or '-'}
Hechos determinantes:
{hechos or '-'}

SENTENCIAS CANDIDATAS (extractos)
{chr(10).join(fichas)}

Evalúa cada candidata como posible precedente del caso, solo con base en su extracto:
1. similitud_hechos (0 a 10): ¿sus antecedentes se parecen a los hechos determinantes del caso?
2. resuelve_fondo (true/false): ¿decide el mismo asunto de fondo? Es false si solo lo menciona, si se decide por razones formales o procesales (improcedencia, técnica de casación, caducidad, hecho superado) o si trata otro problema.
3. puntaje (0 a 100): 80-100 precedente muy análogo que resuelve el fondo; 60-79 resuelve el fondo con hechos parcialmente distintos; 40-59 útil como referencia; menos de 40 no es precedente. Sé exigente.
4. sentido frente a lo que se pide en el caso: "favorable", "desfavorable", "mixto" o "no_aplica".

Devuelve este JSON, con una entrada por cada candidata y usando su referencia [S…]:
{{"evaluaciones": [{{"ref": "S1", "similitud_hechos": 0, "resuelve_fondo": false, "puntaje": 0, "sentido": "no_aplica",
  "decision": "qué decidió la corte, máximo 25 palabras",
  "regla": "la regla o razón de la decisión aplicable al caso, máximo 45 palabras; vacío si no hay",
  "por_que": "semejanzas y diferencias con el caso, máximo 45 palabras"}}]}}"""


def _prompt_sintesis(caso: dict, plan: dict, mejores: list[dict]) -> str:
    lineas = "\n".join(
        f"- [{r['radicado']}] {r['corte']} {r.get('ano')}: puntaje {r['puntaje']}, sentido {r['sentido']}. "
        f"Decisión: {r['decision']} Regla: {r['regla']}"
        for r in mejores
    )
    return f"""Problema jurídico del caso: {plan.get('problema_juridico') or caso['titulo']}
Lo que se pide: {caso.get('pretensiones') or '-'}

Precedentes encontrados (ya evaluados):
{lineas}

Devuelve este JSON:
{{"sintesis": "120 a 220 palabras: qué posición tiene la jurisprudencia sobre el asunto de fondo, qué reglas aplican al caso, si hay posturas favorables y desfavorables o diferencias entre cortes. Cita cada afirmación con el radicado entre corchetes, p. ej. [SL1234-2020]. No inventes sentencias que no estén en la lista.",
  "advertencias": ["0 a 3 advertencias útiles (p. ej. pocos precedentes de una corte, hechos del caso que conviene precisar)"]}}"""


# ---------- Ejecución ----------

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


def _fusionar(listas: list[list[int]], excluir: set[int], limite: int) -> list[tuple[int, float]]:
    puntaje: dict[int, float] = {}
    for lista in listas:
        for pos, pid in enumerate(lista):
            if pid not in excluir:
                puntaje[pid] = puntaje.get(pid, 0) + 1 / (60 + pos)
    return sorted(puntaje.items(), key=lambda x: -x[1])[:limite]


def _base_resultado(f: dict) -> dict:
    return {k: f.get(k) for k in ("corte", "corte_clave", "sala", "tipo", "radicado", "ano", "fecha", "ponente", "tema", "subtema", "radicacion")}


def _correr_consultas(consultas: list[str], caso: dict, limite: int) -> list[list[int]]:
    listas = []
    for c in consultas:
        fts = busqueda.a_consulta_fts(c)
        if not fts:
            continue
        try:
            listas.append(busqueda.candidatos(fts, caso.get("cortes"), caso.get("desde"), caso.get("hasta"), limite))
        except Exception:  # consulta inválida para FTS: se omite
            continue
    return listas


def _excluidas(caso_id: int) -> set[int]:
    ids = set()
    for corte, radicado in casos.descartadas(caso_id):
        pid = busqueda.id_por_radicado(corte, radicado)
        if pid:
            ids.add(pid)
    return ids


def analizar_local(aid: int, caso: dict, amplitud: str) -> None:
    _avance(aid, "Buscando palabras clave del caso", 10)
    texto = f"{caso['titulo']} {caso['descripcion']} {caso.get('pretensiones', '')}"
    claves = palabras_clave(texto)
    if not claves:
        raise ia.ErrorIA("Describe el caso con más detalle: no se encontraron palabras para buscar.")
    consulta = " O ".join(claves)
    casos.actualizar_analisis(aid, planteamiento={"terminos_clave": claves, "consultas": [{"consulta": consulta, "proposito": "palabras más distintivas del caso"}]})
    _avance(aid, "Buscando sentencias", 40)
    listas = _correr_consultas([consulta, " ".join(claves[:4])], caso, 80)
    fusion = _fusionar(listas, _excluidas(caso["id"]), CANDIDATAS[amplitud] // 2)
    maximo = fusion[0][1] if fusion else 1
    resultados = []
    for pid, valor in fusion:
        f = busqueda.ficha(pid)
        plano = _plano(busqueda.leer_texto(pid))
        presentes = [c for c in claves if c in plano]
        resultados.append({
            **_base_resultado(f),
            "puntaje": round(100 * valor / maximo),
            "por_que": "Coincide en: " + ", ".join(presentes[:10]),
            "fragmento": busqueda.fragmento(busqueda.leer_texto(pid), claves[:6], 360),
        })
    casos.actualizar_analisis(aid, resultados=resultados, estado="listo", paso="Listo", progreso=100)


def analizar_ia(aid: int, caso: dict, amplitud: str) -> None:
    uso = _Uso()
    _avance(aid, "La IA está analizando el caso", 5)
    plan, u = ia.chat_json(
        [{"role": "system", "content": SISTEMA}, {"role": "user", "content": _prompt_planteamiento(caso)}], max_tokens=1500
    )
    uso.sumar(u)
    propuestas = []
    for c in (plan.get("consultas") or [])[:8]:
        if isinstance(c, dict) and c.get("consulta"):
            propuestas.append({"consulta": str(c["consulta"]), "proposito": str(c.get("proposito") or "")})
        elif isinstance(c, str) and c.strip():
            propuestas.append({"consulta": c, "proposito": ""})
    texto_caso = f"{caso['titulo']} {caso['descripcion']} {caso.get('pretensiones', '')}"
    claves_locales = palabras_clave(texto_caso, 12)
    if claves_locales:  # red de seguridad con las palabras más distintivas del caso
        propuestas.append({"consulta": " O ".join(claves_locales), "proposito": "palabras más distintivas del caso"})
    plan["consultas"] = propuestas
    consultas = [p["consulta"] for p in propuestas]
    casos.actualizar_analisis(aid, planteamiento=plan)

    _avance(aid, "Buscando sentencias candidatas", 15, uso)
    listas = _correr_consultas(consultas, caso, 50)
    fusion = _fusionar(listas, _excluidas(caso["id"]), CANDIDATAS[amplitud])
    if not fusion:
        casos.actualizar_analisis(aid, resultados=[], estado="listo", paso="Listo", progreso=100,
                                  tokens_entrada=uso.entrada, tokens_salida=uso.salida)
        return

    _avance(aid, f"Leyendo {len(fusion)} sentencias candidatas", 22, uso)
    terminos = list({*claves_locales, *(_plano(t) for t in plan.get("terminos_clave") or [] if isinstance(t, str))})
    terminos = [w for t in terminos for w in re.findall(r"[a-zñ]{4,}", t) if w not in _STOP]
    candidatas = []
    for n, (pid, _) in enumerate(fusion, 1):
        f = busqueda.ficha(pid)
        candidatas.append((f"S{n}", f, extracto(pid, terminos)))

    lotes = [candidatas[i : i + LOTE] for i in range(0, len(candidatas), LOTE)]
    evaluaciones: dict[str, dict] = {}
    hechos_lotes = 0

    def evaluar(lote):
        fichas = [_ficha_texto(ref, f, e) for ref, f, e in lote]
        datos, u = ia.chat_json(
            [{"role": "system", "content": SISTEMA}, {"role": "user", "content": _prompt_evaluacion(caso, plan, fichas)}],
            max_tokens=200 * len(lote) + 300,
        )
        uso.sumar(u)
        return datos.get("evaluaciones") or []

    _avance(aid, f"La IA está evaluando las candidatas (0 de {len(candidatas)})", 25, uso)
    with ThreadPoolExecutor(max_workers=HILOS) as grupo:
        futuros = [grupo.submit(evaluar, lote) for lote in lotes]
        for futuro in as_completed(futuros):
            for ev in futuro.result():
                if isinstance(ev, dict) and ev.get("ref"):
                    evaluaciones[str(ev["ref"]).strip("[] ")] = ev
            hechos_lotes += 1
            hechas = min(hechos_lotes * LOTE, len(candidatas))
            _avance(aid, f"La IA está evaluando las candidatas ({hechas} de {len(candidatas)})",
                    25 + int(65 * hechos_lotes / len(lotes)), uso)

    resultados = []
    for ref, f, e in candidatas:
        ev = evaluaciones.get(ref)
        if not ev:
            continue
        try:
            puntaje = max(0, min(100, int(float(ev.get("puntaje", 0)))))
            similitud = max(0, min(10, int(float(ev.get("similitud_hechos", 0)))))
        except (TypeError, ValueError):
            continue
        sentido = ev.get("sentido") if ev.get("sentido") in ("favorable", "desfavorable", "mixto", "no_aplica") else "no_aplica"
        resultados.append({
            **_base_resultado(f),
            "puntaje": puntaje,
            "similitud_hechos": similitud,
            "resuelve_fondo": bool(ev.get("resuelve_fondo")),
            "sentido": sentido,
            "decision": str(ev.get("decision") or "")[:400],
            "regla": str(ev.get("regla") or "")[:600],
            "por_que": str(ev.get("por_que") or "")[:600],
        })
    resultados.sort(key=lambda r: (-r["puntaje"], -r["similitud_hechos"]))

    mejores = [r for r in resultados if r["puntaje"] >= 50][:12]
    if mejores:
        _avance(aid, "La IA está redactando la síntesis", 93, uso)
        try:
            sintesis, u = ia.chat_json(
                [{"role": "system", "content": SISTEMA}, {"role": "user", "content": _prompt_sintesis(caso, plan, mejores)}],
                max_tokens=900,
            )
            uso.sumar(u)
            plan["sintesis"] = str(sintesis.get("sintesis") or "")
            plan["advertencias"] = [str(a) for a in sintesis.get("advertencias") or []][:3]
        except ia.ErrorIA as exc:
            plan["advertencias"] = [f"No se pudo redactar la síntesis: {exc}"]
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
            casos.actualizar_analisis(aid, estado="error", error=str(exc), paso="Error")
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
