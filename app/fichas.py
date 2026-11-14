"""Fichas neutras de sentencias, elaboradas por la IA SIN conocer el caso.

Separar la lectura de la sentencia de la comparación con el caso evita que
la IA "acomode" la sentencia a la pregunta. Cada ficha trae citas literales
que aquí se verifican contra el texto completo; las que no aparecen quedan
marcadas como no verificadas. Las fichas se guardan en datos/cache_ia.sqlite
y se reutilizan en otros casos (son independientes del caso).
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import busqueda, config, ia
from .texto import marcar_secciones, reflujo_pdf

VERSION = 1
HILOS = 6
CACHE_DB = config.DATOS_DIR / "cache_ia.sqlite"
_bloqueo = threading.Lock()
_local = threading.local()

TIPOS_RESULTADO = {"concede", "niega", "improcedente", "carencia_actual", "casa", "no_casa", "revoca", "confirma",
                   "exequible", "inexequible", "exequible_condicionado", "inhibida", "otro"}
FAVORECE = {"trabajador", "empleador", "accionante", "accionado", "parcial", "no_aplica"}
PAPELES = {"ratio", "reiteracion", "obiter"}


# ---------- Caché ----------

def _conexion() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        config.DATOS_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(CACHE_DB, timeout=30, check_same_thread=False)
        conn.execute("PRAGMA journal_mode = WAL")
        with _bloqueo:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS fichas (corte_clave TEXT, radicado TEXT, version INTEGER, modelo TEXT, "
                "ficha TEXT, creado TEXT, PRIMARY KEY (corte_clave, radicado, version))"
            )
            conn.commit()
        _local.conn = conn
    return conn


def _leer_cache(corte_clave: str, radicado: str) -> dict | None:
    fila = _conexion().execute(
        "SELECT ficha FROM fichas WHERE corte_clave = ? AND radicado = ? AND version = ?", (corte_clave, radicado, VERSION)
    ).fetchone()
    return json.loads(fila[0]) if fila else None


def _guardar_cache(corte_clave: str, radicado: str, modelo: str, ficha: dict) -> None:
    conn = _conexion()
    with _bloqueo:
        conn.execute(
            "INSERT OR REPLACE INTO fichas VALUES (?, ?, ?, ?, ?, ?)",
            (corte_clave, radicado, VERSION, modelo, json.dumps(ficha, ensure_ascii=False), time.strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()


# ---------- Extracto amplio (sin relación con ningún caso) ----------

_RE_HECHOS = re.compile(r"ANTECEDENTES|HECHOS|LA DEMANDA|S[IÍ]NTESIS|ASUNTO|SOLICITUD", re.I)
_RE_FIN_HECHOS = re.compile(r"CONSIDERACIONES|FUNDAMENTOS|COMPETENCIA|PROBLEMA JUR|CARGO|DEMANDA DE CASACI|EL RECURSO", re.I)
_RE_PROBLEMA = re.compile(r"PROBLEMA JUR", re.I)
_RE_CASO = re.compile(r"CASO CONCRETO|AN[AÁ]LISIS DEL CASO|SOLUCI[OÓ]N DEL CASO|EL CASO|ESTUDIO DEL CASO|CASOS? (?:EN )?CONCRETO", re.I)
_RE_CONSIDERACIONES = re.compile(r"CONSIDERACIONES|FUNDAMENTOS", re.I)
_RE_DECISION = re.compile(r"RESUELVE|DECISI[OÓ]N|DECIDE|FALLA", re.I)


def _limpio(bloque: str) -> str:
    bloque = re.sub(r"[*_>|`]+", " ", bloque).replace("#", "")
    return re.sub(r"\s+", " ", bloque).strip()


def _juntar(bloques: list[str]) -> str:
    return "\n".join(_limpio(b) for b in bloques if _limpio(b))


def _recortar(texto: str, maximo: int, cola: int = 0) -> str:
    """Toma el comienzo y, si se pide, el final (donde suele estar la aplicación al caso)."""
    if len(texto) <= maximo:
        return texto
    if not cola:
        return texto[:maximo] + " […]"
    return texto[: maximo - cola] + "\n[…]\n" + texto[-cola:]


def extracto_amplio(texto: str, corte_clave: str) -> dict:
    if corte_clave == "csj":
        texto = reflujo_pdf(texto)
    bloques = [b.strip() for b in marcar_secciones(texto).split("\n\n") if b.strip()]
    titulos = [i for i, b in enumerate(bloques) if b.startswith("#")]
    def titulo(i): return bloques[i]

    decision_i = next((i for i in reversed(titulos) if _RE_DECISION.search(titulo(i))), None)
    fin = decision_i if decision_i is not None else len(bloques)

    hechos_i = next((i for i in titulos if _RE_HECHOS.search(titulo(i)) and i < fin), None)
    inicio_hechos = hechos_i + 1 if hechos_i is not None else min(2, len(bloques))
    fin_hechos = next((i for i in titulos if i > inicio_hechos and _RE_FIN_HECHOS.search(titulo(i))), fin)
    hechos = _recortar(_juntar(bloques[inicio_hechos:fin_hechos]), 5000, cola=1200)

    problema = ""
    problema_i = next((i for i in titulos if _RE_PROBLEMA.search(titulo(i)) and i < fin), None)
    if problema_i is not None:
        problema = _recortar(_juntar(bloques[problema_i + 1 : problema_i + 6]), 1200)

    caso_i = next((i for i in titulos if _RE_CASO.search(titulo(i)) and fin_hechos <= i < fin), None)
    if caso_i is not None:
        analisis = _recortar(_juntar(bloques[caso_i + 1 : fin]), 6500, cola=3500)
    else:
        cons_i = next((i for i in titulos if _RE_CONSIDERACIONES.search(titulo(i)) and fin_hechos <= i < fin), fin_hechos)
        analisis = _recortar(_juntar(bloques[cons_i:fin]), 6500, cola=4500)

    if decision_i is not None:
        decision = _recortar(_juntar(bloques[decision_i + 1 :]), 2500)
    else:
        plano = _limpio(texto)
        m = list(re.finditer(r"RESUELVE|NO CASA|CASA LA SENTENCIA|DECIDE|FALLA", plano))
        decision = plano[m[-1].start() : m[-1].start() + 2500] if m else plano[-2500:]
    return {"hechos": hechos, "problema": problema, "analisis": analisis, "decision": decision}


# ---------- Verificación de citas ----------

def normalizar(texto: str) -> str:
    sin = "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")
    return " ".join(re.findall(r"[a-z0-9ñ]+", sin))


def _tejas(palabras: list[str], n: int = 4) -> set[tuple]:
    return {tuple(palabras[i : i + n]) for i in range(len(palabras) - n + 1)}


class Verificador:
    def __init__(self, texto: str) -> None:
        self.norm = normalizar(texto)
        self.tejas = _tejas(self.norm.split())

    def verificar(self, cita: str) -> bool:
        if not cita:
            return False
        segmentos = [s for s in re.split(r"\.\.\.|…|\[\s*…?\s*\]|\(\s*…\s*\)|\(\.\.\.\)", cita) if s.strip()]
        palabras_total = 0
        for seg in segmentos:
            norm = normalizar(seg)
            palabras = norm.split()
            if len(palabras) < 4:
                continue
            palabras_total += len(palabras)
            if norm in self.norm:
                continue
            tejas = _tejas(palabras)
            if not tejas or len(tejas & self.tejas) / len(tejas) < 0.85:
                return False
        return palabras_total >= 6


# ---------- Prompt ----------

SISTEMA = (
    "Eres relator de jurisprudencia colombiana. Elaboras fichas fieles de sentencias: no interpretas a favor de "
    "nadie, no completas lo que el texto no dice y copias las citas literalmente. Respondes solo con un objeto JSON válido."
)


def _cabecera(f: dict) -> str:
    return (f"{f['corte']} · {f.get('sala') or ''} · {f.get('tipo') or ''} {f['radicado']} · "
            f"{f.get('fecha') or f.get('ano')} · M.P. {f.get('ponente') or '—'}")


def _prompt(f: dict, e: dict) -> str:
    partes = [f"SENTENCIA: {_cabecera(f)}"]
    if f.get("resumen"):
        partes.append(f"SÍNTESIS DE LA RELATORÍA:\n{f['resumen'][:600]}")
    partes.append(f"ANTECEDENTES (extracto):\n{e['hechos'] or '—'}")
    if e["problema"]:
        partes.append(f"PROBLEMA JURÍDICO (extracto):\n{e['problema']}")
    partes.append(f"ANÁLISIS DE LA CORTE (extracto):\n{e['analisis'] or '—'}")
    partes.append(f"PARTE RESOLUTIVA:\n{e['decision'] or '—'}")
    return "\n\n".join(partes) + """

Elabora la ficha de esta sentencia. Devuelve este JSON:
{
  "hechos": ["4 a 10 hechos concretos del caso decidido, incluidos los procesales que pesaron (solicitudes previas, permisos pedidos u otorgados, decisiones de instancia, fechas relevantes); sin nombres de personas"],
  "problema_juridico": "la pregunta que resolvió la Corte, como ella la plantea",
  "resultado": {
    "tipo": "concede | niega | improcedente | carencia_actual | casa | no_casa | revoca | confirma | exequible | inexequible | exequible_condicionado | inhibida | otro",
    "efecto": "qué quedó decidido en una frase. Si confirma o revoca, di qué había decidido el fallo confirmado o revocado (por ejemplo: confirma el fallo que negó el amparo)",
    "favorece_a": "trabajador | empleador | accionante | accionado | parcial | no_aplica",
    "cita": "copia literal de la parte resolutiva, 15 a 60 palabras"
  },
  "decide_fondo": true,
  "motivo_si_no_decide_fondo": "",
  "reglas": [
    {"regla": "formulación fiel de la regla", "papel": "ratio | reiteracion | obiter",
     "cita": "copia literal de la sentencia que sostiene la regla, 20 a 80 palabras"}
  ],
  "normas_aplicadas": ["solo las normas que la Corte aplicó para decidir, no las que apenas mencionó"],
  "temas": ["3 a 6 temas"]
}

Reglas:
- "favorece_a": en controversias laborales usa trabajador o empleador según a quién benefició lo decidido; "no_aplica" en control abstracto.
- "decide_fondo": false si la Corte no resolvió el asunto de fondo (improcedencia, carencia actual, falta de requisitos formales, inhibición, imposibilidad material como la liquidación de la entidad); explica el motivo.
- "papel": "ratio" si la Corte aplicó la regla para decidir este caso; "reiteracion" si solo la expuso en consideraciones generales sin aplicarla de forma determinante; "obiter" si es un comentario de paso.
- 1 a 4 reglas, primero la ratio. Si la sentencia solo transcribe una norma o cita otra sentencia sin aplicarla, no la presentes como ratio.
- Las citas deben ser copias exactas de los extractos: se verificarán automáticamente contra la sentencia. No parafrasees, no unas fragmentos distantes y no corrijas la ortografía."""


def _depurar(datos: dict, verificador: Verificador) -> dict:
    res = datos.get("resultado") if isinstance(datos.get("resultado"), dict) else {}
    tipo = str(res.get("tipo") or "otro").strip().lower()
    favorece = str(res.get("favorece_a") or "no_aplica").strip().lower()
    reglas = []
    for r in datos.get("reglas") or []:
        if not isinstance(r, dict) or not r.get("regla"):
            continue
        papel = str(r.get("papel") or "reiteracion").strip().lower()
        cita = str(r.get("cita") or "").strip()
        reglas.append({
            "regla": str(r["regla"])[:700],
            "papel": papel if papel in PAPELES else "reiteracion",
            "cita": cita[:900],
            "verificada": verificador.verificar(cita),
        })
    cita_res = str(res.get("cita") or "").strip()
    return {
        "hechos": [str(h)[:300] for h in datos.get("hechos") or []][:10],
        "problema_juridico": str(datos.get("problema_juridico") or "")[:600],
        "resultado": {
            "tipo": tipo if tipo in TIPOS_RESULTADO else "otro",
            "efecto": str(res.get("efecto") or "")[:400],
            "favorece_a": favorece if favorece in FAVORECE else "no_aplica",
            "cita": cita_res[:900],
            "verificada": verificador.verificar(cita_res),
        },
        "decide_fondo": bool(datos.get("decide_fondo", True)),
        "motivo_si_no_decide_fondo": str(datos.get("motivo_si_no_decide_fondo") or "")[:300],
        "reglas": reglas[:4],
        "normas_aplicadas": [str(n)[:120] for n in datos.get("normas_aplicadas") or []][:8],
        "temas": [str(t)[:80] for t in datos.get("temas") or []][:6],
    }


def elaborar(pid: int, uso_cb=None) -> dict:
    """Ficha de una sentencia (de la caché si ya existe)."""
    f = busqueda.ficha(pid)
    cache = _leer_cache(f["corte_clave"], f["radicado"])
    if cache:
        return cache
    texto = busqueda.leer_texto(pid)
    e = extracto_amplio(texto, f["corte_clave"])
    datos, uso = ia.chat_json(
        [{"role": "system", "content": SISTEMA}, {"role": "user", "content": _prompt(f, e)}], max_tokens=1800
    )
    if uso_cb:
        uso_cb(uso)
    ficha = _depurar(datos, Verificador(texto))
    _guardar_cache(f["corte_clave"], f["radicado"], ia.estado()["modelo"], ficha)
    return ficha


def elaborar_varias(pids: list[int], uso_cb=None, avance_cb=None) -> tuple[dict[int, dict], list[str]]:
    """Fichas de varias sentencias en paralelo. Devuelve (fichas por id, errores)."""
    fichas: dict[int, dict] = {}
    errores: list[str] = []
    hechas = 0
    with ThreadPoolExecutor(max_workers=HILOS) as grupo:
        futuros = {grupo.submit(elaborar, pid, uso_cb): pid for pid in pids}
        for futuro in as_completed(futuros):
            pid = futuros[futuro]
            try:
                fichas[pid] = futuro.result()
            except ia.ErrorIA as exc:
                errores.append(str(exc))
            hechas += 1
            if avance_cb:
                avance_cb(hechas, len(pids))
    return fichas, errores
