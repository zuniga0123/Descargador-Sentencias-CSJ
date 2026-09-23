"""Índice SQLite local de las providencias descargadas.

Es un derivado: la fuente de verdad son los .md y _metadata.json que se
suben a git. El índice no se sube (supera el límite de 100MB por archivo
de GitHub) y se reconstruye con `python main.py --reconstruir-indice`.
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

-- rowid de providencias_fts = providencias.id, para poder unir resultados.
CREATE VIRTUAL TABLE IF NOT EXISTS providencias_fts USING fts5(
    radicado,
    tema,
    subtema,
    texto_completo,
    tokenize='unicode61 remove_diacritics 2'
);
"""


@contextmanager
def conectar(db_path: Path | None = None):
    db_path = db_path or config.DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def inicializar(db_path: Path | None = None) -> None:
    with conectar(db_path) as conn:
        legado = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'providencias_fts'"
        ).fetchone()
        # La primera versión creó una tabla FTS "contentless" que no permitía
        # saber a qué providencia correspondía cada resultado.
        if legado and "content=''" in legado[0]:
            conn.execute("DROP TABLE providencias_fts")
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
    (providencia_id,) = conn.execute(
        "SELECT id FROM providencias WHERE corte = ? AND radicado = ? AND sub_sala = ?",
        (corte, radicado, sub_sala),
    ).fetchone()
    conn.execute("DELETE FROM providencias_fts WHERE rowid = ?", (providencia_id,))
    conn.execute(
        "INSERT INTO providencias_fts (rowid, radicado, tema, subtema, texto_completo) VALUES (?, ?, ?, ?, ?)",
        (providencia_id, radicado, tema, subtema, texto_completo),
    )
