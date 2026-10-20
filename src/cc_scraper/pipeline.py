"""Enumeración, descarga, clasificación y registro de providencias de la
Corte Constitucional, con el mismo formato que la CSJ
(docs/ESPECIFICACION_UNIFICACION.md)."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone

from csj_scraper import db
from csj_scraper.pipeline import Presupuesto, TiempoAgotado
from csj_scraper.utils import slugify

from . import config
from .areas import asignar_area
from .cliente import CcClient
from .relatoria import ResultadoBusqueda, buscar_por_tipo_y_anio, descargar_documento, obtener_titulaciones

logger = logging.getLogger(__name__)

SIN_TEMA = "Otros - Sin clasificar"
SIN_SUBTEMA = "Sin subtema"
NOMBRE_SALA = {
    "PLENA": "Sala Plena",
    "REVISION": "Sala de Revisión",
    "SEGUIMIENTO": "Sala Especial de Seguimiento",
}


def _slug_corto(texto: str) -> str:
    # Los descriptores oficiales pueden superar los 200 caracteres; Windows
    # limita la ruta completa a 260.
    return slugify(texto)[:60].strip("-") or "sin-nombre"


def _ya_descargada(conn, radicado: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM providencias WHERE corte = ? AND radicado = ? LIMIT 1", (config.CORTE, radicado)
    ).fetchone() is not None


def enumerar(client: CcClient, anio: int, tipo: str, reenumerar: bool = False) -> list[ResultadoBusqueda]:
    ruta = config.ENUMERACION_DIR / f"cc-{anio}-{tipo}.json"
    if ruta.exists() and not reenumerar:
        return [ResultadoBusqueda(**r) for r in json.loads(ruta.read_text(encoding="utf-8"))]
    resultados = buscar_por_tipo_y_anio(client, tipo, anio)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(".tmp")
    tmp.write_text(json.dumps([asdict(r) for r in resultados], ensure_ascii=False), encoding="utf-8")
    tmp.replace(ruta)
    logger.info("Enumeración %s %s: %d providencias", anio, config.TIPOS[tipo], len(resultados))
    return resultados


def _sala(tipo: str, markdown: str) -> str:
    if tipo == "T":
        return "REVISION"
    if tipo == "A":
        inicio = markdown[:4000].lower()
        if "sala especial de seguimiento" in inicio:
            return "SEGUIMIENTO"
        if "de revisión" in inicio or "de revision" in inicio:
            return "REVISION"
    return "PLENA"


def _registrar(conn, meta: dict, cuerpo: str, ruta_md, ruta_metadata) -> None:
    db.registrar_providencia(
        conn,
        corte=meta["corte"],
        sala=meta["sala"],
        sub_sala=meta["sub_sala"],
        tipo_providencia=meta["tipo_providencia"],
        radicado=meta["radicado"],
        ano=meta["ano"],
        fecha_creacion=meta["fecha_creacion"],
        magistrado_ponente=meta["magistrado_ponente"],
        area=meta["area"],
        tema=meta["tema"],
        subtema=meta["subtema"],
        puntaje_clasificacion=meta["puntaje_clasificacion"],
        leyes_o_articulos=meta["leyes_o_articulos"],
        doc_id_origen=meta["doc_id_origen"],
        ruta_markdown=str(ruta_md.relative_to(config.DESTINO)),
        ruta_original=None,
        ruta_metadata=str(ruta_metadata.relative_to(config.DESTINO)),
        fecha_descarga=meta["fecha_descarga"],
        texto_completo=cuerpo,
    )


def procesar(client: CcClient, conn, r: ResultadoBusqueda) -> bool:
    documento = descargar_documento(client, r.url)
    if documento is None:
        logger.warning("%s: el sitio devolvió la página genérica (providencia no publicada)", r.radicado)
        return False
    titulaciones = obtener_titulaciones(client, r.prov_id) if r.prov_id else []
    tema = titulaciones[0]["tema"] if titulaciones else SIN_TEMA
    subtema = (titulaciones[0]["subtema"] if titulaciones else None) or SIN_SUBTEMA
    texto_area = " ".join(f"{t['tema']} {t['subtema'] or ''}" for t in titulaciones)
    area = asignar_area(f"{texto_area} {r.tema_relatoria or ''} {r.resumen or ''}", r.tipo)
    sala = _sala(r.tipo, documento.markdown)
    anio = int(r.fecha_sentencia[:4]) if r.fecha_sentencia else None

    carpeta = config.OUTPUT_ROOT / config.CORTE_DIR_NAME / _slug_corto(area) / _slug_corto(tema) / _slug_corto(subtema)
    carpeta.mkdir(parents=True, exist_ok=True)
    meta = {
        "radicado": r.radicado,
        "corte": config.CORTE,
        "sala": sala,
        "sub_sala": sala,
        "tipo_providencia": "AUTO" if r.tipo == "A" else "SENTENCIA",
        "ano": anio,
        "fecha_creacion": r.fecha_sentencia,
        "magistrado_ponente": documento.magistrado_ponente,
        "area": area,
        "tema": tema,
        "subtema": subtema,
        "puntaje_clasificacion": None,
        "leyes_o_articulos": documento.normas,
        "doc_id_origen": r.url,
        "fecha_descarga": datetime.now(timezone.utc).isoformat(),
        "fuente_clasificacion": "relatoria_oficial" if titulaciones else "sin_titulacion",
        "fecha_providencia": r.fecha_sentencia,
        "fecha_publicacion": r.fecha_publicacion,
        "numero": r.numero,
        "tipo_cc": r.tipo,
        "prov_id": r.prov_id,
        "tema_relatoria": r.tema_relatoria,
        "resumen": r.resumen,
        "titulaciones": titulaciones,
    }
    encabezado = (
        f"# {r.radicado}\n\n"
        f"- **Corte:** {config.CORTE}\n"
        f"- **Sala:** {NOMBRE_SALA[sala]}\n"
        f"- **Magistrado ponente:** {documento.magistrado_ponente or 'No identificado'}\n"
        f"- **Fecha:** {r.fecha_sentencia or 'No identificada'}\n"
        f"- **Tipo de providencia:** {meta['tipo_providencia']} ({config.TIPOS[r.tipo]})\n"
        f"- **Tema:** {tema}\n"
        f"- **Subtema:** {subtema}\n"
        f"- **Normas citadas:** {', '.join(documento.normas) or 'No identificadas'}\n\n"
        "---\n\n"
    )
    ruta_md = carpeta / f"{r.radicado}.md"
    ruta_md.write_text(encabezado + documento.markdown, encoding="utf-8")
    ruta_metadata = carpeta / f"{r.radicado}_metadata.json"
    ruta_metadata.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    _registrar(conn, meta, documento.markdown, ruta_md, ruta_metadata)
    return True


def reconstruir_indice() -> int:
    for sufijo in ("", "-wal", "-shm"):
        config.DB_PATH.with_name(config.DB_PATH.name + sufijo).unlink(missing_ok=True)
    db.inicializar(config.DB_PATH)
    total = 0
    with db.conectar(config.DB_PATH) as conn:
        for ruta_metadata in sorted((config.OUTPUT_ROOT / config.CORTE_DIR_NAME).rglob("*_metadata.json")):
            meta = json.loads(ruta_metadata.read_text(encoding="utf-8"))
            ruta_md = ruta_metadata.with_name(f"{meta['radicado']}.md")
            if ruta_md.exists():
                _, _, cuerpo = ruta_md.read_text(encoding="utf-8").partition("\n---\n\n")
                _registrar(conn, meta, cuerpo, ruta_md, ruta_metadata)
                total += 1
    logger.info("Índice de la Corte Constitucional reconstruido con %d providencias.", total)
    return total


def ejecutar(
    anios: list[int],
    tipos: list[str] | None = None,
    limite: int | None = None,
    max_minutos: float | None = None,
    reenumerar: bool = False,
) -> bool:
    tipos = tipos or list(config.TIPOS)
    presupuesto = Presupuesto(max_minutos)
    if not config.DB_PATH.exists() and any(config.OUTPUT_ROOT.rglob("*_metadata.json")):
        logger.info("No hay índice local pero sí providencias descargadas: reconstruyendo índice...")
        reconstruir_indice()
    db.inicializar(config.DB_PATH)
    client = CcClient()
    nuevos = saltados = 0
    completo = True
    with db.conectar(config.DB_PATH) as conn:
        try:
            for anio in anios:
                for tipo in tipos:
                    presupuesto.verificar()
                    resultados = enumerar(client, anio, tipo, reenumerar=reenumerar)
                    for r in resultados:
                        if limite is not None and nuevos >= limite:
                            logger.info("Límite de %d documentos alcanzado, deteniendo.", limite)
                            raise TiempoAgotado
                        if _ya_descargada(conn, r.radicado):
                            saltados += 1
                            continue
                        presupuesto.verificar()
                        try:
                            hizo = procesar(client, conn, r)
                        except Exception:
                            logger.exception("Error procesando %s (%s)", r.radicado, r.url)
                            continue
                        conn.commit()
                        if hizo:
                            nuevos += 1
                            logger.info("[%d] Descargado %s (%s %s)", nuevos, r.radicado, config.TIPOS[tipo], anio)
        except TiempoAgotado:
            completo = False
    logger.info("Nuevos: %d, ya existentes (saltados): %d", nuevos, saltados)
    logger.info("ESTADO: COMPLETO" if completo else "ESTADO: INCOMPLETO. El avance quedó guardado; vuelve a correr el mismo comando para continuar.")
    return completo
