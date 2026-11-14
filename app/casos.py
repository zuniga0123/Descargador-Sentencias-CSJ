"""Casos, usuarios, análisis de precedentes e historial.

Se guardan en `datos/casos.sqlite`, aparte de la base de sentencias: así
actualizar las sentencias (que reconstruye esa base) no borra los casos.
Las sentencias se referencian por (corte, radicado), que no cambia entre
reconstrucciones, y no por el id interno.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any

from . import config

CASOS_DB = config.DATOS_DIR / "casos.sqlite"
_bloqueo = threading.Lock()
_local = threading.local()

ESQUEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL UNIQUE COLLATE NOCASE,
    creado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS casos (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    titulo TEXT NOT NULL,
    descripcion TEXT NOT NULL DEFAULT '',
    pretensiones TEXT NOT NULL DEFAULT '',
    cortes TEXT NOT NULL DEFAULT '[]',
    desde INTEGER,
    hasta INTEGER,
    archivado INTEGER NOT NULL DEFAULT 0,
    creado TEXT NOT NULL,
    actualizado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analisis (
    id INTEGER PRIMARY KEY,
    caso_id INTEGER NOT NULL REFERENCES casos(id) ON DELETE CASCADE,
    usuario_id INTEGER,
    creado TEXT NOT NULL,
    estado TEXT NOT NULL,            -- en_curso | listo | error
    modo TEXT NOT NULL,              -- ia | local
    paso TEXT,
    progreso INTEGER NOT NULL DEFAULT 0,
    planteamiento TEXT,              -- JSON: problema jurídico, hechos, consultas...
    resultados TEXT,                 -- JSON: lista ordenada de precedentes
    modelo TEXT,
    tokens_entrada INTEGER NOT NULL DEFAULT 0,
    tokens_salida INTEGER NOT NULL DEFAULT 0,
    error TEXT
);
CREATE TABLE IF NOT EXISTS guardadas (
    caso_id INTEGER NOT NULL REFERENCES casos(id) ON DELETE CASCADE,
    corte_clave TEXT NOT NULL,
    radicado TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'precedente',   -- precedente | descartada
    nota TEXT NOT NULL DEFAULT '',
    datos TEXT,                                  -- JSON: explicación de la IA al guardarla
    creado TEXT NOT NULL,
    PRIMARY KEY (caso_id, corte_clave, radicado)
);
CREATE TABLE IF NOT EXISTS historial (
    id INTEGER PRIMARY KEY,
    caso_id INTEGER NOT NULL REFERENCES casos(id) ON DELETE CASCADE,
    usuario_id INTEGER,
    fecha TEXT NOT NULL,
    accion TEXT NOT NULL,
    detalle TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_casos_usuario ON casos (usuario_id, archivado);
CREATE INDEX IF NOT EXISTS idx_analisis_caso ON analisis (caso_id);
CREATE INDEX IF NOT EXISTS idx_historial_caso ON historial (caso_id);
"""


def ahora() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def conexion() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        config.DATOS_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(CASOS_DB, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        with _bloqueo:
            conn.executescript(ESQUEMA)
            _migrar(conn)
        _local.conn = conn
    return conn


# Columnas agregadas después de la primera versión (bases ya creadas).
COLUMNAS_NUEVAS = {
    "posicion": "TEXT NOT NULL DEFAULT 'neutral'",   # trabajador | empleador | neutral
    "recientes": "INTEGER NOT NULL DEFAULT 1",       # preferir sentencias recientes
}


def _migrar(conn: sqlite3.Connection) -> None:
    existentes = {f[1] for f in conn.execute("PRAGMA table_info(casos)")}
    for nombre, definicion in COLUMNAS_NUEVAS.items():
        if nombre not in existentes:
            conn.execute(f"ALTER TABLE casos ADD COLUMN {nombre} {definicion}")
    conn.commit()


POSICIONES = {"trabajador": "la parte trabajadora (demandante o accionante)",
              "empleador": "la parte empleadora (demandada o accionada)",
              "neutral": "ninguna parte: análisis neutral (juez, estudio o docencia)"}


def _escribir(sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
    conn = conexion()
    with _bloqueo:
        cur = conn.execute(sql, params)
        conn.commit()
    return cur


def _caso_dict(fila: sqlite3.Row) -> dict:
    d = dict(fila)
    d["cortes"] = json.loads(d["cortes"] or "[]")
    return d


# ---------- Usuarios ----------

def usuarios() -> list[dict]:
    return [dict(f) for f in conexion().execute("SELECT id, nombre FROM usuarios ORDER BY nombre")]


def crear_usuario(nombre: str) -> dict:
    nombre = " ".join(nombre.split())[:60]
    if not nombre:
        raise ValueError("Escribe un nombre.")
    fila = conexion().execute("SELECT id, nombre FROM usuarios WHERE nombre = ?", (nombre,)).fetchone()
    if fila:
        return dict(fila)
    cur = _escribir("INSERT INTO usuarios (nombre, creado) VALUES (?, ?)", (nombre, ahora()))
    return {"id": cur.lastrowid, "nombre": nombre}


def usuario(uid: int) -> dict | None:
    fila = conexion().execute("SELECT id, nombre FROM usuarios WHERE id = ?", (uid,)).fetchone()
    return dict(fila) if fila else None


# ---------- Casos ----------

CAMPOS_CASO = ("titulo", "descripcion", "pretensiones", "cortes", "desde", "hasta", "archivado", "posicion", "recientes")


def listar_casos(usuario_id: int, archivados: bool = False) -> list[dict]:
    filas = conexion().execute(
        """SELECT c.*,
              (SELECT count(*) FROM guardadas g WHERE g.caso_id = c.id AND g.estado = 'precedente') AS n_guardadas,
              (SELECT count(*) FROM analisis a WHERE a.caso_id = c.id AND a.estado = 'listo') AS n_analisis
           FROM casos c WHERE c.usuario_id = ? AND c.archivado = ? ORDER BY c.actualizado DESC""",
        (usuario_id, int(archivados)),
    ).fetchall()
    return [_caso_dict(f) for f in filas]


def obtener_caso(caso_id: int) -> dict | None:
    fila = conexion().execute("SELECT * FROM casos WHERE id = ?", (caso_id,)).fetchone()
    return _caso_dict(fila) if fila else None


def crear_caso(usuario_id: int, datos: dict) -> dict:
    titulo = (datos.get("titulo") or "").strip()[:200] or "Caso sin título"
    momento = ahora()
    cur = _escribir(
        "INSERT INTO casos (usuario_id, titulo, descripcion, pretensiones, cortes, desde, hasta, posicion, recientes, "
        "creado, actualizado) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            usuario_id, titulo, datos.get("descripcion") or "", datos.get("pretensiones") or "",
            json.dumps(datos.get("cortes") or []), datos.get("desde"), datos.get("hasta"),
            datos.get("posicion") if datos.get("posicion") in POSICIONES else "neutral",
            0 if datos.get("recientes") in (0, False) else 1, momento, momento,
        ),
    )
    registrar(cur.lastrowid, usuario_id, "Creó el caso", titulo)
    return obtener_caso(cur.lastrowid)


def actualizar_caso(caso_id: int, usuario_id: int, datos: dict) -> dict:
    actual = obtener_caso(caso_id)
    if not actual:
        raise KeyError(caso_id)
    cambios = {k: v for k, v in datos.items() if k in CAMPOS_CASO and v != actual.get(k)}
    if not cambios:
        return actual
    if "cortes" in cambios:
        cambios["cortes"] = json.dumps(cambios["cortes"] or [])
    if "posicion" in cambios and cambios["posicion"] not in POSICIONES:
        cambios.pop("posicion")
    if "recientes" in cambios:
        cambios["recientes"] = 1 if cambios["recientes"] else 0
    columnas = ", ".join(f"{k} = ?" for k in cambios)
    _escribir(f"UPDATE casos SET {columnas}, actualizado = ? WHERE id = ?", [*cambios.values(), ahora(), caso_id])
    nombres = {"titulo": "título", "descripcion": "hechos", "pretensiones": "lo que se discute", "cortes": "cortes",
               "desde": "años", "hasta": "años", "archivado": "archivo", "posicion": "parte representada",
               "recientes": "preferencia por sentencias recientes"}
    if "archivado" in cambios:
        registrar(caso_id, usuario_id, "Archivó el caso" if cambios["archivado"] else "Reabrió el caso")
    otros = sorted({nombres[k] for k in cambios if k != "archivado"})
    if otros:
        registrar(caso_id, usuario_id, "Editó el caso", ", ".join(otros))
    return obtener_caso(caso_id)


def eliminar_caso(caso_id: int) -> None:
    _escribir("DELETE FROM casos WHERE id = ?", (caso_id,))


def tocar_caso(caso_id: int) -> None:
    _escribir("UPDATE casos SET actualizado = ? WHERE id = ?", (ahora(), caso_id))


# ---------- Historial ----------

def registrar(caso_id: int, usuario_id: int | None, accion: str, detalle: str = "") -> None:
    _escribir(
        "INSERT INTO historial (caso_id, usuario_id, fecha, accion, detalle) VALUES (?, ?, ?, ?, ?)",
        (caso_id, usuario_id, ahora(), accion, detalle[:500]),
    )


def historial(caso_id: int, limite: int = 200) -> list[dict]:
    filas = conexion().execute(
        """SELECT h.fecha, h.accion, h.detalle, u.nombre AS usuario FROM historial h
           LEFT JOIN usuarios u ON u.id = h.usuario_id WHERE h.caso_id = ? ORDER BY h.id DESC LIMIT ?""",
        (caso_id, limite),
    ).fetchall()
    return [dict(f) for f in filas]


# ---------- Sentencias guardadas ----------

def guardadas(caso_id: int) -> list[dict]:
    filas = conexion().execute(
        "SELECT * FROM guardadas WHERE caso_id = ? ORDER BY estado, creado DESC", (caso_id,)
    ).fetchall()
    salida = []
    for f in filas:
        d = dict(f)
        d["datos"] = json.loads(d["datos"]) if d["datos"] else {}
        salida.append(d)
    return salida


def guardar_sentencia(caso_id: int, usuario_id: int, corte_clave: str, radicado: str, estado: str = "precedente",
                      nota: str | None = None, datos: dict | None = None) -> None:
    previa = conexion().execute(
        "SELECT estado, nota FROM guardadas WHERE caso_id = ? AND corte_clave = ? AND radicado = ?",
        (caso_id, corte_clave, radicado),
    ).fetchone()
    if previa:
        _escribir(
            "UPDATE guardadas SET estado = ?, nota = ?, datos = COALESCE(?, datos) WHERE caso_id = ? AND corte_clave = ? AND radicado = ?",
            (estado, previa["nota"] if nota is None else nota, json.dumps(datos, ensure_ascii=False) if datos else None,
             caso_id, corte_clave, radicado),
        )
    else:
        _escribir(
            "INSERT INTO guardadas (caso_id, corte_clave, radicado, estado, nota, datos, creado) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (caso_id, corte_clave, radicado, estado, nota or "", json.dumps(datos, ensure_ascii=False) if datos else None, ahora()),
        )
    if not previa or previa["estado"] != estado:
        registrar(caso_id, usuario_id, "Guardó como precedente" if estado == "precedente" else "Descartó", radicado)
    if nota is not None and (not previa or previa["nota"] != nota):
        registrar(caso_id, usuario_id, "Escribió una nota", f"{radicado}: {nota[:120]}")
    tocar_caso(caso_id)


def quitar_sentencia(caso_id: int, usuario_id: int, corte_clave: str, radicado: str) -> None:
    _escribir("DELETE FROM guardadas WHERE caso_id = ? AND corte_clave = ? AND radicado = ?", (caso_id, corte_clave, radicado))
    registrar(caso_id, usuario_id, "Quitó de guardadas", radicado)


def descartadas(caso_id: int) -> set[tuple[str, str]]:
    return {
        (f["corte_clave"], f["radicado"])
        for f in conexion().execute("SELECT corte_clave, radicado FROM guardadas WHERE caso_id = ? AND estado = 'descartada'", (caso_id,))
    }


# ---------- Análisis ----------

def crear_analisis(caso_id: int, usuario_id: int | None, modo: str, modelo: str | None) -> int:
    cur = _escribir(
        "INSERT INTO analisis (caso_id, usuario_id, creado, estado, modo, paso, modelo) VALUES (?, ?, ?, 'en_curso', ?, ?, ?)",
        (caso_id, usuario_id, ahora(), modo, "Iniciando", modelo),
    )
    return cur.lastrowid


def actualizar_analisis(analisis_id: int, **campos: Any) -> None:
    if not campos:
        return
    for k in ("planteamiento", "resultados"):
        if k in campos and not isinstance(campos[k], str):
            campos[k] = json.dumps(campos[k], ensure_ascii=False)
    columnas = ", ".join(f"{k} = ?" for k in campos)
    _escribir(f"UPDATE analisis SET {columnas} WHERE id = ?", [*campos.values(), analisis_id])


def _analisis_dict(fila: sqlite3.Row | None) -> dict | None:
    if not fila:
        return None
    d = dict(fila)
    d["planteamiento"] = json.loads(d["planteamiento"]) if d["planteamiento"] else None
    d["resultados"] = json.loads(d["resultados"]) if d["resultados"] else []
    return d


def obtener_analisis(analisis_id: int) -> dict | None:
    return _analisis_dict(conexion().execute("SELECT * FROM analisis WHERE id = ?", (analisis_id,)).fetchone())


def analisis_del_caso(caso_id: int) -> list[dict]:
    filas = conexion().execute(
        "SELECT id, creado, estado, modo, modelo, tokens_entrada, tokens_salida, error, "
        "json_array_length(COALESCE(resultados, '[]')) AS n FROM analisis WHERE caso_id = ? ORDER BY id DESC",
        (caso_id,),
    ).fetchall()
    return [dict(f) for f in filas]


def marcar_interrumpidos() -> None:
    """Al arrancar: los análisis que quedaron a medias (se cerró la app) pasan a error."""
    _escribir(
        "UPDATE analisis SET estado = 'error', error = 'Se interrumpió porque se cerró el buscador.' WHERE estado = 'en_curso'"
    )
