"""Consultas sobre la base unificada: búsqueda con filtros, facetas y lectura.

Está separado del servidor web para que el mismo motor lo pueda usar más
adelante un asistente con IA (DeepSeek u otro): ver `app/ia.py`.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import unicodedata
import zlib
from dataclasses import dataclass, field

from . import config

FILTROS = ("corte", "sala", "tipo", "area", "tema", "subtema", "ponente")
_local = threading.local()


def conexion() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA mmap_size=268435456")
        _local.conn = conn
    return conn


def _sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def a_consulta_fts(texto: str) -> str | None:
    """Convierte lo que escribe la persona en una consulta FTS5 segura.

    - "frase exacta" entre comillas
    - -palabra excluye
    - palabra* busca por prefijo
    - O entre términos para alternativas (estabilidad O fuero)
    - Un radicado (T-760/08, 11001-31-05-...) se busca como frase.
    """
    texto = (texto or "").strip()
    if not texto:
        return None
    partes: list[str] = []
    for m in re.finditer(r'(-?)"([^"]+)"|(\S+)', texto):
        negado, frase, palabra = m.group(1), m.group(2), m.group(3)
        if frase is not None:
            tokens = re.findall(r"\w+", frase)
            if tokens:
                partes.append(("NOT " if negado else "") + '"' + " ".join(tokens) + '"')
            continue
        if palabra.upper() in ("O", "OR"):
            partes.append("OR")
            continue
        negado = palabra.startswith("-") and len(palabra) > 1
        palabra = palabra.lstrip("-")
        prefijo = palabra.endswith("*")
        tokens = re.findall(r"\w+", palabra)
        if not tokens:
            continue
        if len(tokens) > 1:
            termino = '"' + " ".join(tokens) + '"'
        else:
            termino = f'"{tokens[0]}"' + ("*" if prefijo else "")
        partes.append(("NOT " if negado else "") + termino)
    # Limpiar operadores sueltos al inicio/fin o repetidos.
    limpio: list[str] = []
    for p in partes:
        if p == "OR" and (not limpio or limpio[-1] == "OR"):
            continue
        limpio.append(p)
    while limpio and limpio[-1] == "OR":
        limpio.pop()
    if not limpio or all(p.startswith("NOT ") for p in limpio if p != "OR"):
        return None
    # FTS5 no admite NOT al inicio: mover los negados al final.
    positivos = [p for p in limpio if not p.startswith("NOT ")]
    negativos = [p for p in limpio if p.startswith("NOT ")]
    # Agrupar alternativas: "a O b c" debe ser (a O b) Y c, no a O (b Y c).
    grupos: list[list[str]] = []
    unir = False
    for p in positivos:
        if p == "OR":
            unir = bool(grupos)
            continue
        if unir:
            grupos[-1].append(p)
        else:
            grupos.append([p])
        unir = False
    piezas = [g[0] if len(g) == 1 else "(" + " OR ".join(g) + ")" for g in grupos]
    return " ".join(piezas + negativos)


@dataclass
class Busqueda:
    q: str = ""
    corte: list[str] = field(default_factory=list)
    sala: list[str] = field(default_factory=list)
    tipo: list[str] = field(default_factory=list)
    area: list[str] = field(default_factory=list)
    tema: list[str] = field(default_factory=list)
    subtema: list[str] = field(default_factory=list)
    ponente: list[str] = field(default_factory=list)
    desde: int | None = None
    hasta: int | None = None
    orden: str = "relevancia"  # relevancia | recientes | antiguas
    pagina: int = 1
    por_pagina: int = config.RESULTADOS_POR_PAGINA


def _where(b: Busqueda, excluir: str | None = None) -> tuple[str, list]:
    condiciones, params = [], []
    for campo in FILTROS:
        valores = getattr(b, campo)
        if campo == excluir or not valores:
            continue
        columna = "corte_clave" if campo == "corte" else campo
        condiciones.append(f"p.{columna} IN ({','.join('?' * len(valores))})")
        params.extend(valores)
    if b.desde:
        condiciones.append("p.ano >= ?")
        params.append(b.desde)
    if b.hasta:
        condiciones.append("p.ano <= ?")
        params.append(b.hasta)
    return (" AND ".join(condiciones) or "1"), params


def buscar(b: Busqueda) -> dict:
    conn = conexion()
    fts = a_consulta_fts(b.q)
    where, params = _where(b)
    if fts:
        base = "FROM fts JOIN providencias p ON p.id = fts.rowid WHERE fts MATCH ? AND " + where
        base_params = [fts] + params
    else:
        base = "FROM providencias p WHERE " + where
        base_params = params

    total = conn.execute(f"SELECT count(*) {base}", base_params).fetchone()[0]

    if b.orden == "antiguas":
        orden = "p.ano, p.fecha, p.id"
    elif b.orden == "recientes" or not fts:
        orden = "p.ano DESC, p.fecha DESC, p.id DESC"
    else:
        # bm25 con pesos: radicado, ponente, temas (metadatos), texto.
        orden = "bm25(fts, 10.0, 5.0, 3.0, 1.0)"
    desplazamiento = (max(b.pagina, 1) - 1) * b.por_pagina
    filas = conn.execute(
        f"SELECT p.* {base} ORDER BY {orden} LIMIT ? OFFSET ?",
        base_params + [b.por_pagina, desplazamiento],
    ).fetchall()

    resultados = []
    terminos = terminos_resaltado(b.q)
    for f in filas:
        r = dict(f)
        r["normas"] = json.loads(r["normas"] or "[]")
        r.pop("titulaciones", None)
        r["fragmento"] = fragmento(leer_texto(f["id"]), terminos) if terminos else (r.get("resumen") or "")[:400]
        resultados.append(r)

    return {
        "total": total,
        "pagina": b.pagina,
        "por_pagina": b.por_pagina,
        "consulta_fts": fts,
        "resultados": resultados,
        "facetas": facetas(b, fts),
    }


def facetas(b: Busqueda, fts: str | None) -> dict:
    """Conteos por filtro. Cada faceta ignora su propio filtro para que se
    puedan ver (y marcar) las demás opciones."""
    conn = conexion()
    salida: dict[str, list] = {}
    campos = {"corte": "corte_clave", "sala": "sala", "tipo": "tipo", "tema": "tema", "ponente": "ponente", "ano": "ano"}
    for nombre, columna in campos.items():
        where, params = _where(b, excluir=nombre if nombre != "ano" else None)
        if nombre == "ano":
            where, params = _where(Busqueda(**{**b.__dict__, "desde": None, "hasta": None}))
        if fts:
            sql = f"SELECT p.{columna} v, count(*) n FROM fts JOIN providencias p ON p.id = fts.rowid WHERE fts MATCH ? AND {where} GROUP BY v"
            params = [fts] + params
        else:
            sql = f"SELECT p.{columna} v, count(*) n FROM providencias p WHERE {where} GROUP BY v"
        filas = [(r["v"], r["n"]) for r in conn.execute(sql, params) if r["v"] not in (None, "")]
        if nombre == "ano":
            filas.sort()
        else:
            filas.sort(key=lambda x: -x[1])
            if nombre in ("ponente", "tema"):
                filas = filas[:60]
        salida[nombre] = [{"valor": v, "n": n} for v, n in filas]
    return salida


def leer_texto(pid: int) -> str:
    fila = conexion().execute("SELECT md FROM textos WHERE id = ?", (pid,)).fetchone()
    return zlib.decompress(fila[0]).decode("utf-8") if fila else ""


def terminos_resaltado(q: str) -> list[str]:
    if not q:
        return []
    terminos = []
    for m in re.finditer(r'(-?)"([^"]+)"|(\S+)', q):
        if m.group(1) == "-" or (m.group(3) or "").startswith("-"):
            continue
        valor = m.group(2) or m.group(3)
        if valor.upper() in ("O", "OR"):
            continue
        valor = valor.rstrip("*")
        if len(valor) >= 2:
            terminos.append(valor)
    return terminos


def _patron(terminos: list[str]) -> re.Pattern | None:
    piezas = []
    for t in terminos:
        palabras = re.findall(r"\w+", _sin_tildes(t.lower()))
        if palabras:
            piezas.append(r"\W+".join(re.escape(p) for p in palabras))
    return re.compile(r"\b(" + "|".join(piezas) + r")", re.I) if piezas else None


def fragmento(texto: str, terminos: list[str], largo: int = 360) -> str:
    """Trozo del texto alrededor de la primera coincidencia (sin Markdown)."""
    plano = re.sub(r"[#*_>|`]+", " ", texto)
    plano = re.sub(r"\s+", " ", plano)
    patron = _patron(terminos)
    if not patron:
        return plano[:largo]
    m = patron.search(_sin_tildes(plano))
    if not m:
        return plano[:largo]
    inicio = max(0, m.start() - largo // 3)
    trozo = plano[inicio : inicio + largo]
    return ("…" if inicio else "") + trozo + "…"


def providencia(pid: int) -> dict | None:
    fila = conexion().execute("SELECT * FROM providencias WHERE id = ?", (pid,)).fetchone()
    if not fila:
        return None
    r = dict(fila)
    r["normas"] = json.loads(r["normas"] or "[]")
    r["titulaciones"] = json.loads(r["titulaciones"]) if r["titulaciones"] else []
    r["texto"] = leer_texto(pid)
    return r


def buscar_radicado(radicado: str) -> list[dict]:
    """Coincidencia exacta por radicado / número (p. ej. T-760/08, SL1234-2020)."""
    r = radicado.strip()
    filas = conexion().execute(
        "SELECT id, corte, radicado, numero, ano FROM providencias WHERE radicado = ? COLLATE NOCASE "
        "OR numero = ? COLLATE NOCASE OR radicacion = ? LIMIT 10",
        (r, r, re.sub(r"\s+", "", r)),
    ).fetchall()
    return [dict(f) for f in filas]


def estadisticas() -> dict:
    conn = conexion()
    meta = {f["clave"]: f["valor"] for f in conn.execute("SELECT clave, valor FROM meta")}
    por_corte = [
        dict(f)
        for f in conn.execute(
            "SELECT corte_clave, corte, count(*) n, min(ano) desde, max(ano) hasta FROM providencias GROUP BY corte_clave"
        )
    ]
    return {"construida": meta.get("construida"), "cortes": por_corte, "total": sum(c["n"] for c in por_corte)}


# ---------- Apoyo al buscador de precedentes ----------

def candidatos(consulta_fts: str, cortes: list[str] | None = None, desde: int | None = None,
               hasta: int | None = None, limite: int = 40) -> list[int]:
    """Ids de las sentencias más pertinentes para una consulta FTS ya armada."""
    b = Busqueda(corte=cortes or [], desde=desde, hasta=hasta)
    where, params = _where(b)
    filas = conexion().execute(
        f"SELECT p.id FROM fts JOIN providencias p ON p.id = fts.rowid WHERE fts MATCH ? AND {where} "
        "ORDER BY bm25(fts, 10.0, 5.0, 3.0, 1.0) LIMIT ?",
        [consulta_fts, *params, limite],
    ).fetchall()
    return [f[0] for f in filas]


def frecuencias(terminos: list[str]) -> dict[str, int]:
    """En cuántas sentencias aparece cada término (ya normalizado: minúsculas, sin tildes)."""
    conn = conexion()
    if not getattr(_local, "vocab", False):
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp.vocab USING fts5vocab(main, 'fts', 'row')")
        _local.vocab = True
    salida = {}
    for t in set(terminos):
        fila = conn.execute("SELECT doc FROM temp.vocab WHERE term = ?", (t,)).fetchone()
        salida[t] = fila[0] if fila else 0
    return salida


def total_sentencias() -> int:
    return conexion().execute("SELECT count(*) FROM providencias").fetchone()[0]


def id_por_radicado(corte_clave: str, radicado: str) -> int | None:
    fila = conexion().execute(
        "SELECT id FROM providencias WHERE corte_clave = ? AND radicado = ? ORDER BY id LIMIT 1", (corte_clave, radicado)
    ).fetchone()
    return fila[0] if fila else None


def ficha(pid: int) -> dict | None:
    fila = conexion().execute(
        "SELECT id, corte, corte_clave, sala, tipo, radicado, numero, ano, fecha, ponente, tema, subtema, resumen, "
        "radicacion FROM providencias WHERE id = ?", (pid,)
    ).fetchone()
    return dict(fila) if fila else None


def anos(ids: list[int]) -> dict[int, int | None]:
    """Año de cada sentencia (para dar prioridad a las recientes)."""
    if not ids:
        return {}
    salida: dict[int, int | None] = {}
    conn = conexion()
    for i in range(0, len(ids), 500):
        parte = ids[i : i + 500]
        for f in conn.execute(f"SELECT id, ano FROM providencias WHERE id IN ({','.join('?' * len(parte))})", parte):
            salida[f[0]] = f[1]
    return salida
