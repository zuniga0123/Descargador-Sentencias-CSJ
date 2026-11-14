"""Construye la base unificada (datos/jurisprudencia.sqlite) a partir de las
sentencias de la Corte Suprema y de la Corte Constitucional.

Las lee directamente de los ZIP de GitHub (o de carpetas locales) sin
descomprimirlas: así se evitan las rutas largas que Windows no admite.

Uso:
    python -m app.preparar_datos --descargar           # baja los ZIP y construye
    python -m app.preparar_datos                       # usa los ZIP ya descargados
    python -m app.preparar_datos --csj RUTA --cc RUTA  # carpeta o ZIP de cada corte
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
import urllib.request
import zipfile
import zlib
from pathlib import Path
from typing import Iterator

from . import config

SEPARADOR = "\n---\n\n"
TIPOS_CC = {"T": "Tutela", "C": "Constitucionalidad", "SU": "Unificación", "A": "Auto"}
NOMBRE_SALA_CSJ = {"PERMANENTE": "Sala de Casación Laboral", "DESCONGESTION": "Sala de Descongestión Laboral"}

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}
_MESES_RE = "|".join(MESES)
_RE_FECHA = re.compile(
    r"\((\d{1,2})\)\s*de\s*(" + _MESES_RE + r")\s*(?:de|del)\s*(?:dos\s+mil[\w\s]*?|mil\s+novecientos[\w\s]*?)?\s*\(?\s*(\d{4})?",
    re.I,
)
_RE_FECHA_NUM = re.compile(r"\b(\d{1,2})\s+de\s+(" + _MESES_RE + r")\s+de\s+(\d{4})", re.I)
_RE_PONENTE = re.compile(
    r"Magistrad[oa]\s+(?:Ponente|Sustanciador[a]?)\s*[:.]?[\s:*#|]*(?:Dra?\.?\s+|Doctora?\s+)?"
    r"([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñü\. ]{5,60}?)\s*(?:\*\*|\n|\||$|Bogot|Santaf)"
)
_RE_RADICACION = re.compile(r"Radicaci[oó]n\s*(?:n\.?\s*[°ºo]\.?|No\.?|N°|número)?\s*:?\s*(\d[\d\-\s]{3,40}\d)", re.I)

SCHEMA = """
CREATE TABLE providencias (
    id INTEGER PRIMARY KEY,
    corte TEXT NOT NULL,
    corte_clave TEXT NOT NULL,
    sala TEXT,
    tipo TEXT,
    radicado TEXT NOT NULL,
    numero TEXT,
    ano INTEGER,
    fecha TEXT,
    ponente TEXT,
    area TEXT,
    tema TEXT,
    subtema TEXT,
    normas TEXT,
    resumen TEXT,
    titulaciones TEXT,
    radicacion TEXT,
    url_fuente TEXT,
    caracteres INTEGER
);
CREATE TABLE textos (id INTEGER PRIMARY KEY, md BLOB NOT NULL);
-- Índice de texto sin copia del contenido (rowid = providencias.id): el
-- texto ya está comprimido en `textos`, así la base pesa mucho menos.
CREATE VIRTUAL TABLE fts USING fts5(
    radicado, ponente, temas, texto,
    content='', tokenize='unicode61 remove_diacritics 2'
);
CREATE TABLE meta (clave TEXT PRIMARY KEY, valor TEXT);
"""

INDICES = """
CREATE INDEX idx_corte ON providencias (corte_clave, ano);
CREATE INDEX idx_ano ON providencias (ano);
CREATE INDEX idx_area ON providencias (area);
CREATE INDEX idx_tema ON providencias (tema);
CREATE INDEX idx_tipo ON providencias (tipo);
CREATE INDEX idx_ponente ON providencias (ponente);
CREATE INDEX idx_radicado ON providencias (radicado);
"""


def descargar(url: str, destino: Path) -> Path:
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_suffix(destino.suffix + ".parcial")
    for intento in range(1, 4):
        try:
            print(f"Descargando {destino.name} (puede tardar varios minutos)...", flush=True)
            with urllib.request.urlopen(url, timeout=120) as resp, open(temporal, "wb") as salida:
                bajado, siguiente_aviso = 0, 0
                while bloque := resp.read(1024 * 1024):
                    salida.write(bloque)
                    bajado += len(bloque)
                    if bajado >= siguiente_aviso:
                        print(f"  {bajado / 1e6:,.0f} MB", flush=True)
                        siguiente_aviso += 50 * 1024 * 1024
            temporal.replace(destino)
            print(f"  Listo: {destino.stat().st_size / 1e6:,.0f} MB", flush=True)
            return destino
        except OSError as exc:
            print(f"  Falló el intento {intento}/3: {exc}", flush=True)
            time.sleep(5 * intento)
    sys.exit(f"No se pudo descargar {url}. Revisa tu conexión a internet y vuelve a intentarlo.")


def iterar_documentos(origen: Path, carpeta: str) -> Iterator[tuple[dict, str]]:
    """Recorre (metadata, markdown) de un ZIP de GitHub o de una carpeta local."""
    if origen.is_file():
        with zipfile.ZipFile(origen) as z:
            nombres = [n for n in z.namelist() if carpeta in n]
            existentes = set(nombres)
            for nombre in nombres:
                if not nombre.endswith("_metadata.json"):
                    continue
                md = nombre[: -len("_metadata.json")] + ".md"
                if md not in existentes:
                    continue
                yield json.loads(z.read(nombre).decode("utf-8")), z.read(md).decode("utf-8")
        return
    raiz = origen / carpeta if (origen / carpeta).is_dir() else origen
    for ruta in raiz.rglob("*_metadata.json"):
        md = ruta.with_name(ruta.name[: -len("_metadata.json")] + ".md")
        if md.exists():
            yield json.loads(ruta.read_text(encoding="utf-8")), md.read_text(encoding="utf-8")


def extraer_fecha(texto: str, ano: int | None) -> str | None:
    inicio = " ".join(texto[:4000].split())
    m = _RE_FECHA.search(inicio)
    if m:
        dia, mes, anio = int(m.group(1)), MESES[m.group(2).lower()], int(m.group(3)) if m.group(3) else ano
    else:
        m = _RE_FECHA_NUM.search(inicio)
        if not m:
            return None
        dia, mes, anio = int(m.group(1)), MESES[m.group(2).lower()], int(m.group(3))
    if not anio or not 1 <= dia <= 31 or (ano and abs(anio - ano) > 1):
        return None
    return f"{anio:04d}-{mes:02d}-{dia:02d}"


def ponente_en_texto(cuerpo: str) -> str | None:
    m = _RE_PONENTE.search(cuerpo[:40000])
    if not m:
        return None
    nombre = m.group(1).strip(" .")
    return nombre if 2 <= len(nombre.split()) <= 6 else None


def _limpiar_ponente(nombre: str | None) -> str | None:
    if not nombre:
        return None
    return re.sub(r"^(?:Dra?|Doctora?)(?:\.\s*|\s+)", "", nombre.strip(), flags=re.I).strip(" .,") or None


_MINUSCULAS = {"de", "del", "la", "las", "los", "y", "e"}


def normalizar_ponentes(conn: sqlite3.Connection) -> None:
    """Unifica variantes del mismo nombre (mayúsculas, tildes, espacios o
    letras de más por errores de la fuente) para que el filtro por ponente no
    muestre a la misma persona varias veces."""
    import difflib
    import unicodedata
    from collections import Counter, defaultdict

    def clave(nombre: str) -> str:
        sin = "".join(c for c in unicodedata.normalize("NFD", nombre) if unicodedata.category(c) != "Mn")
        return re.sub(r"[^a-z]", "", sin.lower())

    def bonito(nombre: str) -> str:
        if nombre.upper() != nombre:
            return " ".join(nombre.split())
        palabras = nombre.lower().split()
        return " ".join(p if (p in _MINUSCULAS and i) else p.capitalize() for i, p in enumerate(palabras))

    filas = conn.execute("SELECT ponente, count(*) FROM providencias WHERE ponente IS NOT NULL GROUP BY ponente").fetchall()
    grupos: dict[str, Counter] = defaultdict(Counter)
    for nombre, n in filas:
        limpio = re.sub(r"^Comun[ií]quese\s+y\s+\w+\s+|\s+(?:y\s+)?(?:Dra?|Doctora?)\.?$|\s+Bogot[aá].*$|[\s\-.,]+$", "", nombre, flags=re.I)
        grupos[clave(limpio)][limpio] += n
    totales = {k: sum(v.values()) for k, v in grupos.items()}
    frecuentes = sorted((k for k, n in totales.items() if n >= 20 and len(k) >= 12), key=len, reverse=True)
    destino: dict[str, str] = {}
    for k, n in totales.items():
        if n >= 20 or not k:
            continue
        # Variante rara: unirla al nombre frecuente con el que empieza o al más parecido.
        candidato = next((f for f in frecuentes if k.startswith(f)), None)
        prefijo_de = [f for f in frecuentes if f.startswith(k)]
        if not candidato and len(k) >= 6 and len(prefijo_de) == 1:  # nombre cortado
            candidato = prefijo_de[0]
        if not candidato:
            parecidos = difflib.get_close_matches(k, frecuentes, n=1, cutoff=0.9)
            candidato = parecidos[0] if parecidos else None
        if candidato:
            destino[k] = candidato

    def elegir(variantes: Counter) -> str:
        # Preferir tipo título con tildes; luego la más frecuente.
        return bonito(max(variantes, key=lambda v: (v.upper() != v, sum(ord(c) > 127 for c in v), variantes[v])))

    final_por_clave = {k: elegir(v) for k, v in grupos.items()}
    cambios = []
    for nombre, _ in filas:
        limpio = re.sub(r"^Comun[ií]quese\s+y\s+\w+\s+|\s+(?:y\s+)?(?:Dra?|Doctora?)\.?$|\s+Bogot[aá].*$|[\s\-.,]+$", "", nombre, flags=re.I)
        k = clave(limpio)
        final = final_por_clave[destino.get(k, k)]
        if final != nombre:
            cambios.append((final, nombre))
    conn.executemany("UPDATE providencias SET ponente = ? WHERE ponente = ?", cambios)


def fila(meta: dict, cuerpo: str, clave: str) -> dict:
    ano = meta.get("ano")
    if clave == "cc":
        tipo = TIPOS_CC.get(meta.get("tipo_cc"), meta.get("tipo_providencia", "").title())
        sala = {"PLENA": "Sala Plena", "REVISION": "Sala de Revisión", "SEGUIMIENTO": "Sala Especial de Seguimiento"}.get(
            meta.get("sala"), meta.get("sala")
        )
        fecha = meta.get("fecha_providencia") or meta.get("fecha_creacion")
        numero = meta.get("numero") or meta["radicado"]
        url = meta.get("doc_id_origen")
        radicacion = None
    else:
        tipo = meta.get("tipo_providencia", "SENTENCIA").title()
        sala = NOMBRE_SALA_CSJ.get(meta.get("sub_sala"), meta.get("sub_sala"))
        fecha = extraer_fecha(cuerpo, ano)
        numero = meta["radicado"]
        url = None
        m = _RE_RADICACION.search(" ".join(cuerpo[:3000].split()))
        radicacion = re.sub(r"\s+", "", m.group(1)) if m else None
    titulaciones = meta.get("titulaciones") or []
    temas = " ".join(
        filter(
            None,
            [meta.get("area"), meta.get("tema"), meta.get("subtema"), meta.get("tema_relatoria"), meta.get("resumen")]
            + [f"{t.get('tema', '')} {t.get('subtema') or ''}" for t in titulaciones],
        )
    )
    return {
        "corte": meta["corte"],
        "corte_clave": clave,
        "sala": sala,
        "tipo": tipo,
        "radicado": meta["radicado"],
        "numero": numero,
        "ano": ano,
        "fecha": fecha,
        "ponente": _limpiar_ponente(meta.get("magistrado_ponente") or ponente_en_texto(cuerpo)),
        "area": meta.get("area"),
        "tema": meta.get("tema"),
        "subtema": meta.get("subtema"),
        "normas": json.dumps(meta.get("leyes_o_articulos") or [], ensure_ascii=False),
        "resumen": meta.get("resumen"),
        "titulaciones": json.dumps(titulaciones, ensure_ascii=False) if titulaciones else None,
        "radicacion": radicacion,
        "url_fuente": url,
        "caracteres": len(cuerpo),
        "_temas": temas,
    }


def construir(origenes: dict[str, Path], destino: Path = config.DB_PATH) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_name(destino.name + ".construyendo")
    temporal.unlink(missing_ok=True)
    conn = sqlite3.connect(temporal)
    conn.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;" + SCHEMA)
    columnas = [
        "corte", "corte_clave", "sala", "tipo", "radicado", "numero", "ano", "fecha", "ponente", "area",
        "tema", "subtema", "normas", "resumen", "titulaciones", "radicacion", "url_fuente", "caracteres",
    ]
    sql_prov = f"INSERT INTO providencias ({', '.join(columnas)}) VALUES ({', '.join('?' * len(columnas))})"
    inicio = time.monotonic()
    conteos = {}
    for clave, origen in origenes.items():
        fuente = config.FUENTES[clave]
        print(f"Procesando {fuente['nombre']} desde {origen.name}...", flush=True)
        n = 0
        for meta, md in iterar_documentos(origen, fuente["carpeta"]):
            _, sep, cuerpo = md.partition(SEPARADOR)
            if not sep:
                cuerpo = md
            datos = fila(meta, cuerpo, clave)
            cur = conn.execute(sql_prov, [datos[c] for c in columnas])
            pid = cur.lastrowid
            conn.execute("INSERT INTO textos (id, md) VALUES (?, ?)", (pid, zlib.compress(cuerpo.encode("utf-8"), 6)))
            conn.execute(
                "INSERT INTO fts (rowid, radicado, ponente, temas, texto) VALUES (?, ?, ?, ?, ?)",
                (pid, f"{datos['radicado']} {datos['numero']} {datos['radicacion'] or ''}", datos["ponente"], datos["_temas"], cuerpo),
            )
            n += 1
            if n % 2000 == 0:
                conn.commit()
                print(f"  {n:,} sentencias ({time.monotonic() - inicio:,.0f} s)", flush=True)
        conteos[clave] = n
        print(f"  {fuente['nombre']}: {n:,} sentencias", flush=True)
    conn.commit()
    normalizar_ponentes(conn)
    print("Optimizando índices (unos minutos)...", flush=True)
    conn.executescript(INDICES)
    conn.execute("INSERT INTO fts(fts) VALUES('optimize')")
    conn.executemany(
        "INSERT INTO meta (clave, valor) VALUES (?, ?)",
        [("construida", time.strftime("%Y-%m-%d %H:%M")), ("conteos", json.dumps(conteos))],
    )
    conn.commit()
    conn.execute("ANALYZE")
    conn.commit()
    conn.close()
    temporal.replace(destino)
    total = sum(conteos.values())
    print(
        f"Base lista: {total:,} sentencias, {destino.stat().st_size / 1e9:.2f} GB, "
        f"en {(time.monotonic() - inicio) / 60:.1f} min -> {destino}",
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--descargar", action="store_true", help="Bajar de GitHub los ZIP más recientes antes de construir.")
    parser.add_argument("--csj", type=Path, help="Carpeta o ZIP con las sentencias de la Corte Suprema.")
    parser.add_argument("--cc", type=Path, help="Carpeta o ZIP con las sentencias de la Corte Constitucional.")
    parser.add_argument("--borrar-zip", action="store_true", help="Borrar los ZIP descargados al terminar.")
    args = parser.parse_args()

    origenes: dict[str, Path] = {}
    for clave in ("csj", "cc"):
        explicito = getattr(args, clave)
        zip_local = config.DESCARGAS_DIR / config.FUENTES[clave]["zip_nombre"]
        if explicito:
            origenes[clave] = explicito
        elif args.descargar or not zip_local.exists():
            origenes[clave] = descargar(config.FUENTES[clave]["zip_url"], zip_local)
        else:
            origenes[clave] = zip_local
    construir(origenes)
    if args.borrar_zip:
        for clave, origen in origenes.items():
            if origen.parent == config.DESCARGAS_DIR and origen.suffix == ".zip":
                origen.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
