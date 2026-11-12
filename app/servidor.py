"""Servidor local del buscador de jurisprudencia.

    python -m app.servidor            # solo este computador (http://localhost:8000)
    python -m app.servidor --red      # también otros equipos de la misma red
"""

from __future__ import annotations

import argparse
import re
import socket
import threading
import webbrowser
from typing import Annotated

import markdown
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import busqueda, config, ia

WEB_DIR = config.APP_DIR / "web"
app = FastAPI(title="Buscador de jurisprudencia", docs_url="/api/docs", redoc_url=None)

# Párrafos cortos que en la práctica son títulos de sección aunque la fuente
# no los marque como tales (frecuente en la Corte Constitucional).
_PALABRAS_SECCION = (
    "ANTECEDENTES|HECHOS|LA DEMANDA|CONTESTACI[OÓ]N|PRETENSIONES|PRUEBAS|"
    "CONSIDERACIONES|FUNDAMENTOS|PROBLEMA JUR[IÍ]DICO|COMPETENCIA|DECISI[OÓ]N|RESUELVE|"
    "S[IÍ]NTESIS|CASO CONCRETO|EL CASO|SALVAMENTO DE VOTO|ACLARACI[OÓ]N DE VOTO|"
    "INTERVENCIONES|CONCEPTO DEL PROCURADOR|NORMA DEMANDADA|TEXTO DE LA NORMA|"
    "SENTENCIA (?:DE PRIMERA|DE SEGUNDA|IMPUGNADA|RECURRIDA)|EL RECURSO|LA OPOSICI[OÓ]N|"
    "CARGO|ACTUACI[OÓ]N|TR[AÁ]MITE|DECISIONES? (?:JUDICIALES|DE INSTANCIA)|ALCANCE DE LA IMPUGNACI[OÓ]N|"
    "DEMANDA DE CASACI[OÓ]N|ASUNTO|REFERENCIA"
)
_RE_TITULO = re.compile(
    r"^(?:\*\*)?\s*(?:(?:[IVXL]{1,6}|\d{1,2}|[A-H])[\.\-\)]\s*)?(?:" + _PALABRAS_SECCION + r")\b[^\n]{0,80}$",
    re.I,
)
_RE_MAYUS = re.compile(r"^(?:\*\*)?\s*(?:[IVXL]{1,6}[\.\-]\s+)[A-ZÁÉÍÓÚÑ ,\.:;\-]{4,90}(?:\*\*)?$")


_RE_ESPECIAL = re.compile(r"^(?:#|\||>|[-*+]\s|\d{1,3}[.)]\s|[IVXL]{1,6}[.)]\s)")
_FIN_ORACION = tuple(".:;?!»\"”)")


def _clave_linea(linea: str) -> str:
    return re.sub(r"\d+\s*$", "#", linea.strip())


def reflujo_pdf(texto: str) -> str:
    """Las sentencias de la Corte Suprema vienen de PDF: cada renglón quedó
    como párrafo y se intercalan encabezados de página. Aquí se quitan esos
    encabezados repetidos y se unen los renglones de un mismo párrafo."""
    from collections import Counter

    bloques = [b.strip() for b in texto.split("\n\n")]
    cortos = Counter(_clave_linea(b) for b in bloques if b and len(b) < 70 and "\n" not in b)
    repetidos = {k for k, n in cortos.items() if n >= 3 and not k.startswith("#") and len(k) > 2}
    salida: list[str] = []
    for b in bloques:
        if not b or _clave_linea(b) in repetidos or re.fullmatch(r"\d{1,3}", b):
            continue
        previo = salida[-1] if salida else ""
        es_mayus = lambda x: sum(c.isalpha() for c in x) >= 4 and x.upper() == x
        unir = (
            previo
            and "\n" not in previo
            and "\n" not in b
            and not _RE_ESPECIAL.match(previo)
            and not _RE_ESPECIAL.match(b)
            and not es_mayus(previo)
            and not (es_mayus(b) and len(b) < 90)
            and (not previo.endswith(_FIN_ORACION) or b[:1].islower())
        )
        if unir:
            salida[-1] = previo[:-1] + b if previo.endswith("-") and b[:1].islower() else previo + " " + b
        else:
            salida.append(b)
    return "\n\n".join(salida)


def marcar_secciones(texto: str) -> str:
    bloques = texto.split("\n\n")
    for i, bloque in enumerate(bloques):
        b = bloque.strip()
        if not b or b.startswith("#") or "\n" in b or len(b) > 110:
            continue
        limpio = re.sub(r"\*+|\s*\(\d+\)$", "", b).strip(" #").rstrip(":.")
        es_mayus = limpio.upper() == limpio and sum(c.isalpha() for c in limpio) >= 5
        if _RE_MAYUS.match(b) or (es_mayus and _RE_TITULO.match(limpio)):
            bloques[i] = "### " + limpio
    return "\n\n".join(bloques)


def a_html(texto: str) -> tuple[str, list[dict]]:
    md = markdown.Markdown(extensions=["tables", "toc", "sane_lists"], extension_configs={"toc": {"toc_depth": "2-5"}})
    # El texto viene de la fuente: se escapa cualquier HTML incrustado.
    html = md.convert(marcar_secciones(texto.replace("<", "&lt;")))
    indice: list[dict] = []

    def aplanar(tokens):
        for t in tokens:
            indice.append({"id": t["id"], "titulo": t["name"], "nivel": t["level"]})
            aplanar(t["children"])

    aplanar(md.toc_tokens)
    return html, indice


def _lista(valor: list[str] | None) -> list[str]:
    return [v for v in (valor or []) if v]


@app.get("/api/estado")
def estado():
    if not config.DB_PATH.exists():
        return {"lista": False, "mensaje": "Aún no se ha preparado la base. Ejecuta actualizar.bat."}
    return {"lista": True, **busqueda.estadisticas(), "ia": ia.estado()}


@app.get("/api/buscar")
def buscar(
    q: str = "",
    corte: Annotated[list[str] | None, Query()] = None,
    sala: Annotated[list[str] | None, Query()] = None,
    tipo: Annotated[list[str] | None, Query()] = None,
    area: Annotated[list[str] | None, Query()] = None,
    tema: Annotated[list[str] | None, Query()] = None,
    subtema: Annotated[list[str] | None, Query()] = None,
    ponente: Annotated[list[str] | None, Query()] = None,
    desde: int | None = None,
    hasta: int | None = None,
    orden: str = "relevancia",
    pagina: int = Query(1, ge=1, le=500),
):
    b = busqueda.Busqueda(
        q=q, corte=_lista(corte), sala=_lista(sala), tipo=_lista(tipo), area=_lista(area), tema=_lista(tema),
        subtema=_lista(subtema), ponente=_lista(ponente), desde=desde, hasta=hasta, orden=orden, pagina=pagina,
    )
    try:
        resultado = busqueda.buscar(b)
    except Exception as exc:  # consulta FTS mal formada u otro error de SQLite
        raise HTTPException(400, f"No se pudo interpretar la búsqueda: {exc}") from exc
    resultado["exactas"] = busqueda.buscar_radicado(q) if q and len(q) < 40 and pagina == 1 else []
    return resultado


@app.get("/api/providencia/{pid}")
def ver(pid: int, q: str = ""):
    p = busqueda.providencia(pid)
    if not p:
        raise HTTPException(404, "No existe esa providencia.")
    texto = p.pop("texto")
    p["html"], p["indice"] = a_html(reflujo_pdf(texto) if p["corte_clave"] == "csj" else texto)
    p["terminos"] = busqueda.terminos_resaltado(q)
    return p


@app.get("/api/providencia/{pid}/md")
def descargar_md(pid: int):
    p = busqueda.providencia(pid)
    if not p:
        raise HTTPException(404, "No existe esa providencia.")
    nombre = re.sub(r"[^\w\-]+", "_", p["radicado"]) + ".md"
    encabezado = f"# {p['radicado']}\n\n- Corte: {p['corte']}\n- Sala: {p['sala']}\n- Fecha: {p['fecha'] or p['ano']}\n- Ponente: {p['ponente']}\n\n---\n\n"
    texto = reflujo_pdf(p["texto"]) if p["corte_clave"] == "csj" else p["texto"]
    return PlainTextResponse(
        encabezado + texto,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


class Pregunta(BaseModel):
    pregunta: str
    ids: list[int] = []


@app.post("/api/ia/preguntar")
def preguntar(datos: Pregunta):
    if not ia.estado()["activa"]:
        raise HTTPException(400, "La IA no está configurada.")
    if datos.ids:
        contexto = []
        for pid in datos.ids[:8]:
            p = busqueda.providencia(pid)
            if p:
                contexto.append({**p, "fragmento": busqueda.fragmento(p["texto"], busqueda.terminos_resaltado(datos.pregunta), 3000)})
    else:
        r = busqueda.buscar(busqueda.Busqueda(q=datos.pregunta, por_pagina=6))
        contexto = r["resultados"]
    return {"respuesta": ia.preguntar(datos.pregunta, contexto), "fuentes": [c["radicado"] for c in contexto]}


@app.get("/")
def inicio():
    return FileResponse(WEB_DIR / "index.html")


app.mount("/", StaticFiles(directory=WEB_DIR), name="web")


def ip_local() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="Buscador de jurisprudencia")
    parser.add_argument("--red", action="store_true", help="Permitir acceso desde otros equipos de la red local.")
    parser.add_argument("--puerto", type=int, default=config.PUERTO)
    parser.add_argument("--no-abrir", action="store_true", help="No abrir el navegador automáticamente.")
    args = parser.parse_args()

    if not config.DB_PATH.exists():
        print("\nTodavía no está la base de datos. Ejecuta primero actualizar.bat\n")
    host = "0.0.0.0" if args.red else config.HOST
    url = f"http://localhost:{args.puerto}"
    print(f"\n  Buscador listo en {url}")
    if args.red:
        print(f"  Desde otros equipos de la red: http://{ip_local()}:{args.puerto}")
    print("  Para cerrarlo, cierra esta ventana (o Ctrl+C).\n")
    if not args.no_abrir:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=host, port=args.puerto, log_level="warning")


if __name__ == "__main__":
    main()
