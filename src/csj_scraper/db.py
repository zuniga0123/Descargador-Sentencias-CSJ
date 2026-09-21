"""Índice SQLite de las providencias descargadas.

El esquema usa nombres de columna compatibles con el proyecto hermano de
Corte Constitucional (mismo patrón: radicado, corte, fecha, tema, subtema,
área, ruta_archivo) para poder unir ambos índices más adelante, más las
columnas propias de la CSJ (sala/sub_sala, magistrado ponente, leyes
citadas).
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS providencias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    corte TEXT NOT NULL,
    sala TEXT NOT NULL,
    sub_sala TEXT NOT NULL,
    tipo_providencia TEXT,
    radicado TEXT NOT NULL,
    ano INTEGER,
    fecha_creacion TEXT,
    magistrado_ponente TEXT,
    area TEXT,
    tema TEXT,
    subtema TEXT,
    puntaje_clasificacion INTEGER,
    leyes_o_articulos TEXT,
    doc_id_origen TEXT NOT NULL,
    ruta_markdown TEXT,
    ruta_original TEXT,
    ruta_metadata TEXT,
    fecha_descarga TEXT NOT NULL,
    UNIQUE (corte, radicado, sub_sala)
);

CREATE INDEX IF NOT EXISTS idx_providencias_tema ON providencias (tema, subtema);
CREATE INDEX IF NOT EXISTS idx_providencias_ano ON providencias (ano);
CREATE INDEX IF NOT EXISTS idx_providencias_sub_sala ON providencias (sub_sala);

CREATE VIRTUAL TABLE IF NOT EXISTS providencias_fts USING fts5(
    radicado,
    tema,
    subtema,
    texto_completo,
    content='',
    tokenize='unicode61'
);
"""


@contextmanager
def conectar(db_path: Path = config.DB_PATH):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def inicializar(db_path: Path = config.DB_PATH) -> None:
    with conectar(db_path) as conn:
        conn.executescript(SCHEMA)


def ya_descargada(conn: sqlite3.Connection, corte: str, radicado: str, sub_sala: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM providencias WHERE corte = ? AND radicado = ? AND sub_sala = ? LIMIT 1",
        (corte, radicado, sub_sala),
    ).fetchone()
    return row is not None


def registrar_providencia(
    conn: sqlite3.Connection,
    *,
    corte: str,
    sala: str,
    sub_sala: str,
    tipo_providencia: str | None,
    radicado: str,
    ano: int | None,
    fecha_creacion: str | None,
    magistrado_ponente: str | None,
    area: str,
    tema: str,
    subtema: str,
    puntaje_clasificacion: int,
    leyes_o_articulos: list[str],
    doc_id_origen: str,
    ruta_markdown: str,
    ruta_original: str | None,
    ruta_metadata: str,
    fecha_descarga: str,
    texto_completo: str,
) -> None:
    conn.execute(
        """
        INSERT INTO providencias (
            corte, sala, sub_sala, tipo_providencia, radicado, ano,
            fecha_creacion, magistrado_ponente, area, tema, subtema,
            puntaje_clasificacion, leyes_o_articulos, doc_id_origen,
            ruta_markdown, ruta_original, ruta_metadata, fecha_descarga
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (corte, radicado, sub_sala) DO UPDATE SET
            tipo_providencia = excluded.tipo_providencia,
            ano = excluded.ano,
            fecha_creacion = excluded.fecha_creacion,
            magistrado_ponente = excluded.magistrado_ponente,
            area = excluded.area,
            tema = excluded.tema,
            subtema = excluded.subtema,
            puntaje_clasificacion = excluded.puntaje_clasificacion,
            leyes_o_articulos = excluded.leyes_o_articulos,
            doc_id_origen = excluded.doc_id_origen,
            ruta_markdown = excluded.ruta_markdown,
            ruta_original = excluded.ruta_original,
            ruta_metadata = excluded.ruta_metadata,
            fecha_descarga = excluded.fecha_descarga
        """,
        (
            corte,
            sala,
            sub_sala,
            tipo_providencia,
            radicado,
            ano,
            fecha_creacion,
            magistrado_ponente,
            area,
            tema,
            subtema,
            puntaje_clasificacion,
            json.dumps(leyes_o_articulos, ensure_ascii=False),
            doc_id_origen,
            ruta_markdown,
            ruta_original,
            ruta_metadata,
            fecha_descarga,
        ),
    )
    conn.execute(
        "DELETE FROM providencias_fts WHERE radicado = ?",
        (radicado,),
    )
    conn.execute(
        "INSERT INTO providencias_fts (radicado, tema, subtema, texto_completo) VALUES (?, ?, ?, ?)",
        (radicado, tema, subtema, texto_completo),
    )
