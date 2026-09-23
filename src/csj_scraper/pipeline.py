"""Orquesta la enumeración, descarga, clasificación y registro de
providencias de la Sala de Casación Laboral / Sala de Descongestión
Laboral de la Corte Suprema de Justicia.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import config, db
from .api_client import CsjApiClient
from .html_to_markdown import clean_contenttext_to_markdown
from .taxonomy import clasificar
from .utils import extension_desde_titulo, radicado_desde_titulo, slugify

logger = logging.getLogger(__name__)

CORTE = "Corte Suprema de Justicia"


@dataclass
class DocumentoEnumerado:
    radicado: str
    doc_id: str
    extension: str
    ano: int | None
    fecha_creacion: str | None
    doctor: str | None
    tipo_providencia: str | None
    leyes_o_articulos: list[str] = field(default_factory=list)
    sub_sala: str = "DESCONOCIDA"


def _determinar_sub_sala(doc_id: str) -> str:
    doc_id_upper = doc_id.upper()
    if "/LABORAL/DESCONGESTION/" in doc_id_upper:
        return "DESCONGESTION"
    if "/LABORAL/PERMANENTE/" in doc_id_upper:
        return "PERMANENTE"
    return "DESCONOCIDA"


def enumerar_radicados(
    client: CsjApiClient, year: str, tipo_providencia: str, sala: str = config.SALA
) -> dict[str, DocumentoEnumerado]:
    """Recorre todas las páginas de resultados para (year, tipo_providencia)
    y devuelve un radicado -> DocumentoEnumerado (deduplicado, prefiere la
    entrada en PDF cuando el mismo radicado aparece en varios formatos)."""
    encontrados: dict[str, DocumentoEnumerado] = {}
    start = 0
    total = None
    pagina = 0
    while total is None or start < total:
        resultado = client.search(year=year, tipo_providencia=tipo_providencia, start=start, sala=sala)
        total = resultado["numOfResults"]
        resultados = resultado["searchResults"]
        if not resultados:
            break
        for r in resultados:
            radicado = radicado_desde_titulo(r["title"])
            ext = extension_desde_titulo(r["title"])
            existente = encontrados.get(radicado)
            if existente is not None and existente.extension == "pdf":
                continue
            encontrados[radicado] = DocumentoEnumerado(
                radicado=radicado,
                doc_id=r["id"],
                extension=ext,
                ano=r.get("ano"),
                fecha_creacion=r.get("fechaCreacion"),
                doctor=r.get("doctor"),
                tipo_providencia=r.get("autoSentencia"),
                leyes_o_articulos=r.get("leyesOArticulos") or [],
                sub_sala=_determinar_sub_sala(r["id"]),
            )
        pagina += 1
        start += config.RESULTS_PER_PAGE
        if pagina % 20 == 0:
            logger.info(
                "  ... %s %s %s: página %d, %d/%d resultados, %d radicados únicos",
                year, tipo_providencia, sala, pagina, min(start, total), total, len(encontrados),
            )
    logger.info(
        "Enumeración %s %s %s completa: %d radicados únicos (%d resultados crudos)",
        year, tipo_providencia, sala, len(encontrados), total or 0,
    )
    return encontrados


def _carpeta_destino(sub_sala: str, tema: str, subtema: str):
    sub_sala_dir = config.SUB_SALAS.get(sub_sala, config.SUB_SALA_DESCONOCIDA)
    return config.OUTPUT_ROOT / config.CORTE_DIR_NAME / sub_sala_dir / slugify(tema) / slugify(subtema)


def procesar_documento(
    client: CsjApiClient,
    conn,
    doc: DocumentoEnumerado,
    sala: str = config.SALA,
    forzar: bool = False,
    descargar_original: bool = True,
) -> bool:
    """Descarga, clasifica y registra un documento. Devuelve True si hizo
    trabajo nuevo, False si ya estaba descargado y se saltó."""
    if not forzar and db.ya_descargada(conn, CORTE, doc.radicado, doc.sub_sala):
        return False

    contenido = client.get_full_content(doc.doc_id, sala=sala, text=config.QUERY_COMODIN)
    markdown = clean_contenttext_to_markdown(contenido["contentText"])
    clasificacion = clasificar(markdown, doc.leyes_o_articulos)

    carpeta = _carpeta_destino(doc.sub_sala, clasificacion.tema, clasificacion.subtema)
    carpeta.mkdir(parents=True, exist_ok=True)

    ruta_md = carpeta / f"{doc.radicado}.md"
    encabezado = (
        f"# {doc.radicado}\n\n"
        f"- **Corte:** {CORTE}\n"
        f"- **Sala:** {config.SUB_SALA_NOMBRE_LEGIBLE.get(doc.sub_sala, doc.sub_sala.title())}\n"
        f"- **Magistrado ponente:** {doc.doctor or 'No identificado'}\n"
        f"- **Fecha:** {doc.fecha_creacion or 'No identificada'}\n"
        f"- **Tipo de providencia:** {doc.tipo_providencia or 'No identificado'}\n"
        f"- **Tema:** {clasificacion.tema}\n"
        f"- **Subtema:** {clasificacion.subtema}\n"
        f"- **Normas citadas:** {', '.join(doc.leyes_o_articulos) or 'No identificadas'}\n\n"
        "---\n\n"
    )
    ruta_md.write_text(encabezado + markdown, encoding="utf-8")

    ruta_original = None
    if descargar_original:
        try:
            contenido_bin, _content_type = client.download_file(doc.doc_id)
            ruta_original = carpeta / f"{doc.radicado}.{doc.extension}"
            ruta_original.write_bytes(contenido_bin)
        except Exception:
            logger.exception("No se pudo descargar el archivo original de %s", doc.radicado)

    metadata = {
        "radicado": doc.radicado,
        "corte": CORTE,
        "sala": "LABORAL",
        "sub_sala": doc.sub_sala,
        "tipo_providencia": doc.tipo_providencia,
        "ano": doc.ano,
        "fecha_creacion": doc.fecha_creacion,
        "magistrado_ponente": doc.doctor,
        "area": clasificacion.area,
        "tema": clasificacion.tema,
        "subtema": clasificacion.subtema,
        "puntaje_clasificacion": clasificacion.puntaje,
        "leyes_o_articulos": doc.leyes_o_articulos,
        "doc_id_origen": doc.doc_id,
        "fecha_descarga": datetime.now(timezone.utc).isoformat(),
    }
    ruta_metadata = carpeta / f"{doc.radicado}_metadata.json"
    ruta_metadata.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    db.registrar_providencia(
        conn,
        corte=CORTE,
        sala="LABORAL",
        sub_sala=doc.sub_sala,
        tipo_providencia=doc.tipo_providencia,
        radicado=doc.radicado,
        ano=doc.ano,
        fecha_creacion=doc.fecha_creacion,
        magistrado_ponente=doc.doctor,
        area=clasificacion.area,
        tema=clasificacion.tema,
        subtema=clasificacion.subtema,
        puntaje_clasificacion=clasificacion.puntaje,
        leyes_o_articulos=doc.leyes_o_articulos,
        doc_id_origen=doc.doc_id,
        ruta_markdown=str(ruta_md.relative_to(config.PROJECT_ROOT)),
        ruta_original=str(ruta_original.relative_to(config.PROJECT_ROOT)) if ruta_original else None,
        ruta_metadata=str(ruta_metadata.relative_to(config.PROJECT_ROOT)),
        fecha_descarga=metadata["fecha_descarga"],
        texto_completo=markdown,
    )
    return True


def reconstruir_indice() -> int:
    """Regenera indice.sqlite desde cero a partir de los .md y
    _metadata.json en disco (que son la fuente de verdad en git)."""
    for sufijo in ("", "-wal", "-shm"):
        config.DB_PATH.with_name(config.DB_PATH.name + sufijo).unlink(missing_ok=True)
    db.inicializar()
    total = 0
    with db.conectar() as conn:
        for ruta_metadata in sorted((config.OUTPUT_ROOT / config.CORTE_DIR_NAME).rglob("*_metadata.json")):
            meta = json.loads(ruta_metadata.read_text(encoding="utf-8"))
            ruta_md = ruta_metadata.with_name(f"{meta['radicado']}.md")
            if not ruta_md.exists():
                logger.warning("Falta el Markdown de %s, se omite", meta["radicado"])
                continue
            _, _, cuerpo = ruta_md.read_text(encoding="utf-8").partition("\n---\n\n")
            originales = [
                p for p in ruta_metadata.parent.glob(f"{meta['radicado']}.*") if p.suffix in (".pdf", ".doc", ".docx")
            ]
            db.registrar_providencia(
                conn,
                corte=meta["corte"],
                sala=meta["sala"],
                sub_sala=meta["sub_sala"],
                tipo_providencia=meta.get("tipo_providencia"),
                radicado=meta["radicado"],
                ano=meta.get("ano"),
                fecha_creacion=meta.get("fecha_creacion"),
                magistrado_ponente=meta.get("magistrado_ponente"),
                area=meta["area"],
                tema=meta["tema"],
                subtema=meta["subtema"],
                puntaje_clasificacion=meta.get("puntaje_clasificacion", 0),
                leyes_o_articulos=meta.get("leyes_o_articulos", []),
                doc_id_origen=meta["doc_id_origen"],
                ruta_markdown=str(ruta_md.relative_to(config.PROJECT_ROOT)),
                ruta_original=str(originales[0].relative_to(config.PROJECT_ROOT)) if originales else None,
                ruta_metadata=str(ruta_metadata.relative_to(config.PROJECT_ROOT)),
                fecha_descarga=meta["fecha_descarga"],
                texto_completo=cuerpo,
            )
            total += 1
    logger.info("Índice reconstruido con %d providencias.", total)
    return total


def ejecutar(
    anios: list[str],
    tipos: list[str] | None = None,
    sala: str = config.SALA,
    limite: int | None = None,
    forzar: bool = False,
    descargar_original: bool = True,
) -> None:
    tipos = tipos or config.TIPOS_PROVIDENCIA
    # El índice no viaja en git: en un clon nuevo hay que regenerarlo para
    # que la corrida no vuelva a descargar lo que ya está en los archivos.
    if not config.DB_PATH.exists() and any(config.OUTPUT_ROOT.rglob("*_metadata.json")):
        logger.info("No hay índice local pero sí providencias descargadas: reconstruyendo índice...")
        reconstruir_indice()
    db.inicializar()
    client = CsjApiClient()
    procesados = 0
    saltados = 0
    with db.conectar() as conn:
        for year in anios:
            for tipo in tipos:
                logger.info("=== Enumerando %s / %s / %s ===", year, tipo, sala)
                documentos = enumerar_radicados(client, year, tipo, sala=sala)
                for radicado, doc in documentos.items():
                    if limite is not None and procesados >= limite:
                        logger.info("Límite de %d documentos alcanzado, deteniendo.", limite)
                        return
                    try:
                        hizo_trabajo = procesar_documento(
                            client, conn, doc, sala=sala, forzar=forzar, descargar_original=descargar_original
                        )
                    except Exception:
                        logger.exception("Error procesando %s (%s)", radicado, doc.doc_id)
                        continue
                    if hizo_trabajo:
                        procesados += 1
                        logger.info("[%d] Descargado %s (%s / %s)", procesados, radicado, doc.sub_sala, tipo)
                    else:
                        saltados += 1
    logger.info("Listo. Nuevos: %d, ya existentes (saltados): %d", procesados, saltados)
