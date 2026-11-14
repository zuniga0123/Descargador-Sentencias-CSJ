"""Red de citas entre sentencias (capa determinista, sin IA).

Extrae del texto completo (notas al pie incluidas) las sentencias citadas:
  Corte Constitucional: T-760 de 2008, T-760/08, SU-061 de 2023, SU.061/23, C-355-06, T-999A de 2005
  Corte Suprema:        SL1234-2020, CSJ SL2586 de 2020, STL123-2021, AL45-2019,
                        CSJ SL, 25 mar. 2003, rad. 20026 (forma antigua)
y las normaliza al formato de radicado de la base (T-760-08, SU061-23, SL1234-2020).

El índice (datos/citas.sqlite) permite ir hacia atrás (a quién cita una
sentencia) y hacia adelante (quién la cita). Se construye una vez después
de preparar la base: `python -m app.citas`.
"""

from __future__ import annotations

import re
import sqlite3
import sys
import threading
import time
from dataclasses import dataclass

from . import busqueda, config
from .texto import marcar_secciones

CITAS_DB = config.DATOS_DIR / "citas.sqlite"
_local = threading.local()

# --- Expresiones ---
_ANO = r"(?:de\s+|del\s+año\s+|/|-|–)\s*(\d{4}|\d{2})\b"
RE_CC = re.compile(r"(?<![A-Za-z])(SU|T|C)\s?[-–.‑]?\s?(\d{1,4})\s?([A-Ca-c])?\s*" + _ANO)
RE_CSJ = re.compile(r"(?<![A-Za-z])(SL|STL|AL|SP|STP|SC|STC)\s?(\d{1,6})\s?(?:-|–|\s+de\s+)\s?((?:19|20)\d{2})\b")
RE_CSJ_ANTIGUA = re.compile(
    r"(?:CSJ\s+(?:SL|AL)[,\s]+)?(\d{1,2})\s+(ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)[a-z]*\.?\s+(?:de\s+)?((?:19|20)\d{2})"
    r"[,\s]+rad(?:icaci[oó]n)?\.?\s*(?:n\.?\s*[°º]?\s*|No\.?\s*)?(\d{4,6})", re.I)
RE_LLAMADA = re.compile(r"\[\[(\d+)\]\]\(#_ftn(\d+)\)")
RE_NOTA = re.compile(r"\[\[(\d+)\]\]\(#_ftnref(\d+)\)")
_RE_SALVAMENTO = re.compile(r"SALVAMENTO|ACLARACI[OÓ]N DE VOTO|SALVO EL VOTO|ACLARO EL VOTO", re.I)
_RE_ANTECEDENTES = re.compile(r"ANTECEDENTES|HECHOS|DEMANDA|CONTESTACI|SENTENCIA DE (?:PRIMERA|SEGUNDA)|FALLO|DECISI[OÓ]N(?:ES)? (?:DE INSTANCIA|JUDICIAL|IMPUGNADA)|RECURSO|CARGO|IMPUGNACI|INTERVENCI|CONCEPTO|PRUEBAS|ACTUACI|TRÁMITE|TRAMITE|SOLICITUD|RÉPLICA|REPLICA|OPOSICI", re.I)
_RE_CONSIDERACIONES = re.compile(r"CONSIDERACIONES|FUNDAMENTOS|PROBLEMA|CASO CONCRETO|AN[AÁ]LISIS|COMPETENCIA|S[IÍ]NTESIS", re.I)
_RE_DECISION = re.compile(r"RESUELVE|DECISI[OÓ]N$|DECIDE|FALLA", re.I)


def normalizar_cc(tipo: str, numero: str, letra: str | None, ano: str) -> str:
    tipo = tipo.upper()
    yy = ano[-2:]
    num = numero.lstrip("0").zfill(3)
    letra = (letra or "").upper()
    return f"SU{num}{letra}-{yy}" if tipo == "SU" else f"{tipo}-{num}{letra}-{yy}"


@dataclass
class Cita:
    corte: str          # cc | csj
    radicado: str       # normalizado como en la base (o "rad:NNNNN" para la forma antigua de la CSJ)
    original: str
    posicion: int       # posición en el texto
    en_nota: bool
    seccion: str        # antecedentes | consideraciones | decision | salvamento | otro


def _secciones(texto: str) -> list[tuple[int, str]]:
    """Posiciones donde empieza cada sección (según los títulos detectados)."""
    marcas = []
    for m in re.finditer(r"(?m)^#{1,6}\s*(.+)$", marcar_secciones(texto)):
        titulo = m.group(1)
        # Se ubica el título en el texto original (marcar_secciones solo antepone '#').
        pos = texto.find(titulo.strip()[:40])
        if pos < 0:
            continue
        if _RE_SALVAMENTO.search(titulo):
            tipo = "salvamento"
        elif _RE_DECISION.search(titulo):
            tipo = "decision"
        elif _RE_CONSIDERACIONES.search(titulo):
            tipo = "consideraciones"
        elif _RE_ANTECEDENTES.search(titulo):
            tipo = "antecedentes"
        else:
            continue
        marcas.append((pos, tipo))
    # Los salvamentos suelen ir al final sin título claro: se buscan en el texto.
    for m in re.finditer(r"(?i)\bSALVAMENTO DE VOTO\b|\bACLARACI[OÓ]N DE VOTO\b", texto):
        if m.start() > len(texto) * 0.5:
            marcas.append((m.start(), "salvamento"))
            break
    return sorted(marcas)


def _seccion_en(marcas: list[tuple[int, str]], pos: int) -> str:
    actual = "otro"
    for inicio, tipo in marcas:
        if inicio <= pos:
            actual = tipo
        else:
            break
    return actual


def extraer(texto: str, propio: str | None = None) -> list[Cita]:
    """Todas las citas a sentencias en un texto. `propio` excluye la autocita del encabezado."""
    marcas = _secciones(texto)
    # Rango de cada nota al pie (texto de la nota) y dónde se llamó en el cuerpo.
    notas = [(m.start(), m.group(1)) for m in RE_NOTA.finditer(texto)]
    llamadas = {m.group(1): m.start() for m in RE_LLAMADA.finditer(texto)}
    inicio_notas = notas[0][0] if notas else len(texto)

    def ubicar(pos: int) -> tuple[bool, int]:
        """(¿está en una nota?, posición en el cuerpo donde se llamó la nota)."""
        if pos < inicio_notas:
            return False, pos
        numero = None
        for inicio, n in notas:
            if inicio <= pos:
                numero = n
            else:
                break
        return True, llamadas.get(numero, pos)

    citas: list[Cita] = []
    for m in RE_CC.finditer(texto):
        tipo, numero, letra, ano = m.groups()
        if len(ano) == 4 and not 1992 <= int(ano) <= 2100:
            continue
        if len(numero) > 4 or int(numero) == 0:
            continue
        rad = normalizar_cc(tipo, numero, letra, ano)
        if rad == propio:
            continue
        en_nota, cuerpo = ubicar(m.start())
        citas.append(Cita("cc", rad, m.group(0).strip(), m.start(), en_nota, _seccion_en(marcas, cuerpo)))
    for m in RE_CSJ.finditer(texto):
        tipo, numero, ano = m.groups()
        rad = f"{tipo.upper()}{numero}-{ano}"
        if rad == propio or (propio and m.start() < 1500 and rad.startswith("SL") and propio.startswith(rad)):
            continue
        en_nota, cuerpo = ubicar(m.start())
        citas.append(Cita("csj", rad, m.group(0).strip(), m.start(), en_nota, _seccion_en(marcas, cuerpo)))
    for m in RE_CSJ_ANTIGUA.finditer(texto):
        en_nota, cuerpo = ubicar(m.start())
        citas.append(Cita("csj", f"rad:{m.group(4)}", m.group(0).strip(), m.start(), en_nota, _seccion_en(marcas, cuerpo)))
    return citas


def contexto(texto: str, cita: Cita, largo: int = 420) -> str:
    """Párrafo donde aparece la cita; si está en nota, también la frase del cuerpo que la llama."""
    inicio = texto.rfind("\n\n", 0, cita.posicion) + 2
    fin = texto.find("\n\n", cita.posicion)
    parrafo = texto[inicio : fin if fin > 0 else None]
    if len(parrafo) > largo:
        rel = cita.posicion - inicio
        desde = max(0, rel - largo // 2)
        parrafo = ("…" if desde else "") + parrafo[desde : desde + largo] + "…"
    return re.sub(r"\s+", " ", re.sub(r"\[\[\d+\]\]\(#_ftn(?:ref)?\d+\)", "", parrafo)).strip()


# ---------- Índice ----------

ESQUEMA = """
CREATE TABLE IF NOT EXISTS citas (
    origen_corte TEXT NOT NULL,
    origen_radicado TEXT NOT NULL,
    origen_ano INTEGER,
    destino_corte TEXT NOT NULL,
    destino_radicado TEXT NOT NULL,
    veces INTEGER NOT NULL,
    en_nota INTEGER NOT NULL,
    en_consideraciones INTEGER NOT NULL,
    en_antecedentes INTEGER NOT NULL,
    en_salvamento INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (clave TEXT PRIMARY KEY, valor TEXT);
"""


def conexion() -> sqlite3.Connection | None:
    conn = getattr(_local, "conn", None)
    if conn is None:
        if not CITAS_DB.exists():
            return None
        conn = sqlite3.connect(f"file:{CITAS_DB}?mode=ro", uri=True, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        _local.conn = conn
    return conn


def disponible() -> bool:
    return CITAS_DB.exists()


def construir(avance=None) -> dict:
    """Recorre toda la base y guarda quién cita a quién. Tarda unos minutos."""
    config.DATOS_DIR.mkdir(parents=True, exist_ok=True)
    temporal = CITAS_DB.with_name(CITAS_DB.name + ".construyendo")
    temporal.unlink(missing_ok=True)
    salida = sqlite3.connect(temporal)
    salida.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;" + ESQUEMA)
    base = busqueda.conexion()
    filas = base.execute("SELECT p.id, p.corte_clave, p.radicado, p.ano, t.md FROM providencias p JOIN textos t ON t.id = p.id")
    import zlib
    inicio, n, total_citas = time.monotonic(), 0, 0
    total = busqueda.total_sentencias()
    lote = []
    for pid, corte, radicado, ano, md in filas:
        texto = zlib.decompress(md).decode("utf-8")
        agregadas: dict[tuple[str, str], list[int]] = {}
        for c in extraer(texto, radicado):
            k = (c.corte, c.radicado)
            a = agregadas.setdefault(k, [0, 0, 0, 0, 0])
            a[0] += 1
            a[1] += c.en_nota
            a[2] += c.seccion in ("consideraciones", "decision")
            a[3] += c.seccion == "antecedentes"
            a[4] += c.seccion == "salvamento"
        for (dc, dr), a in agregadas.items():
            lote.append((corte, radicado, ano, dc, dr, *a))
        total_citas += len(agregadas)
        n += 1
        if len(lote) > 20000:
            salida.executemany("INSERT INTO citas VALUES (?,?,?,?,?,?,?,?,?,?)", lote)
            lote = []
        if avance and n % 2000 == 0:
            avance(n, total)
    salida.executemany("INSERT INTO citas VALUES (?,?,?,?,?,?,?,?,?,?)", lote)
    salida.executescript("""
        CREATE INDEX idx_origen ON citas (origen_corte, origen_radicado);
        CREATE INDEX idx_destino ON citas (destino_corte, destino_radicado);
    """)
    meta_base = {r[0]: r[1] for r in base.execute("SELECT clave, valor FROM meta")}
    salida.executemany("INSERT INTO meta VALUES (?, ?)", [
        ("construida", time.strftime("%Y-%m-%d %H:%M")), ("base", meta_base.get("construida", "")),
        ("sentencias", str(n)), ("relaciones", str(total_citas))])
    salida.commit()
    salida.close()
    temporal.replace(CITAS_DB)
    _local.conn = None
    return {"sentencias": n, "relaciones": total_citas, "segundos": round(time.monotonic() - inicio)}


def citadas_por(corte: str, radicado: str) -> list[dict]:
    conn = conexion()
    if not conn:
        return []
    return [dict(r) for r in conn.execute(
        "SELECT destino_corte, destino_radicado, veces, en_nota, en_consideraciones, en_antecedentes, en_salvamento "
        "FROM citas WHERE origen_corte = ? AND origen_radicado = ?", (corte, radicado))]


def que_la_citan(corte: str, radicado: str) -> list[dict]:
    conn = conexion()
    if not conn:
        return []
    return [dict(r) for r in conn.execute(
        "SELECT origen_corte, origen_radicado, origen_ano, veces, en_nota, en_consideraciones, en_antecedentes, en_salvamento "
        "FROM citas WHERE destino_corte = ? AND destino_radicado = ? ORDER BY origen_ano DESC", (corte, radicado))]


def resolver(corte: str, radicado: str) -> int | None:
    """Id en la base de una sentencia citada (None si no está)."""
    if radicado.startswith("rad:"):
        fila = busqueda.conexion().execute(
            "SELECT id FROM providencias WHERE corte_clave = 'csj' AND radicado LIKE ? ORDER BY id LIMIT 1",
            (radicado[4:] + "(%",)).fetchone()
        return fila[0] if fila else None
    return busqueda.id_por_radicado(corte, radicado)


if __name__ == "__main__":
    print("Construyendo la red de citas (unos minutos)…", flush=True)
    r = construir(lambda n, t: print(f"  {n:,} de {t:,}", flush=True))
    print(f"Listo: {r['sentencias']:,} sentencias, {r['relaciones']:,} relaciones de cita, {r['segundos']} s", file=sys.stdout)


# ---------- Votos particulares ----------

_RE_VOTO_TITULO = re.compile(
    r"(SALVAMENTO|ACLARACI[OÓ]N)\s+(PARCIAL\s+)?DE\s+VOTO\s+(?:CONJUNTO\s+)?(?:DEL?|DE\s+LA|DE\s+LOS|DE\s+LAS)\s+"
    r"(?:H(?:ONORABLE)?\.?\s+)?(?:MAGISTRAD[OA]S?|CONJUE[ZC]E?S?A?)\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s\.]{5,90}?)"
    r"(?=\s+(?:A\s+LA|AL|EN\s+LA|FRENTE|RESPECTO|CON\s+RELACI|SENTENCIA|RADICACI|REF)\b|[,:;\(]|$)")
_RE_VOTO_FIRMA = re.compile(
    r"([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s\.]{5,60}?)\s+(?:Magistrad[oa]|Conjuez[a]?|MAGISTRAD[OA])\s*(?:\(e\)\s*)?"
    r"(?:Con|CON|con)\s+(salvamento|aclaraci[oó]n|SALVAMENTO|ACLARACI[OÓ]N)\s+(parcial\s+|PARCIAL\s+)?de\s+voto", re.I)


def votos_particulares(texto: str) -> list[dict]:
    """Salvamentos y aclaraciones de voto con el nombre de quien los firma."""
    plano = re.sub(r"\s+", " ", re.sub(r"[*_#|]+", " ", texto))
    votos: dict[tuple[str, str], dict] = {}
    for m in _RE_VOTO_TITULO.finditer(plano):
        tipo = "salvamento" if m.group(1).upper().startswith("S") else "aclaracion"
        for nombre in re.split(r"\s+Y\s+", " ".join(m.group(3).split()).strip(" .")):
            if len(nombre.split()) >= 2:
                votos.setdefault((tipo, nombre.upper()), {"tipo": tipo, "parcial": bool(m.group(2)), "magistrado": nombre.title()})
    for m in _RE_VOTO_FIRMA.finditer(plano):
        nombre = " ".join(m.group(1).split()).strip(" .")
        if len(nombre.split()) < 2 or nombre.upper() != nombre:
            continue
        tipo = "salvamento" if m.group(2).lower().startswith("s") else "aclaracion"
        votos.setdefault((tipo, nombre.upper()), {"tipo": tipo, "parcial": bool(m.group(3)), "magistrado": nombre.title()})
    return list(votos.values())
