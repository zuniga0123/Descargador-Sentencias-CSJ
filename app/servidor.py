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

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import busqueda, casos, config, ia, informes, precedentes
from .texto import a_html, reflujo_pdf

WEB_DIR = config.APP_DIR / "web"
app = FastAPI(title="Buscador de jurisprudencia", docs_url="/api/docs", redoc_url=None)

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


# ---------- IA (configuración: solo desde este mismo computador) ----------

def _solo_local(request: Request) -> None:
    if request.client and request.client.host not in ("127.0.0.1", "::1", "localhost", "testclient"):
        raise HTTPException(403, "La configuración de la IA solo se puede cambiar en el computador donde corre el buscador.")


class ConfigIA(BaseModel):
    clave: str | None = None
    modelo: str | None = None
    borrar_clave: bool = False


@app.get("/api/ia/estado")
def ia_estado(request: Request):
    host = request.client.host if request.client else ""
    return {**ia.estado(), "puede_configurar": host in ("127.0.0.1", "::1", "localhost", "testclient")}


@app.post("/api/ia/config")
def ia_config(datos: ConfigIA, request: Request):
    _solo_local(request)
    try:
        return ia.guardar_config(datos.clave, datos.modelo, datos.borrar_clave)
    except ia.ErrorIA as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/ia/probar")
def ia_probar(request: Request):
    _solo_local(request)
    try:
        return ia.probar()
    except ia.ErrorIA as exc:
        raise HTTPException(400, str(exc)) from exc


# ---------- Usuarios y casos ----------

class NuevoUsuario(BaseModel):
    nombre: str


class DatosCaso(BaseModel):
    usuario_id: int
    titulo: str | None = None
    descripcion: str | None = None
    pretensiones: str | None = None
    cortes: list[str] | None = None
    desde: int | None = None
    hasta: int | None = None
    archivado: int | None = None


class Analizar(BaseModel):
    usuario_id: int
    amplitud: str = "normal"


class Guardar(BaseModel):
    usuario_id: int
    corte_clave: str
    radicado: str
    estado: str = "precedente"
    nota: str | None = None
    datos: dict | None = None


def _caso_o_404(caso_id: int) -> dict:
    caso = casos.obtener_caso(caso_id)
    if not caso:
        raise HTTPException(404, "No existe ese caso.")
    return caso


@app.get("/api/usuarios")
def listar_usuarios():
    return casos.usuarios()


@app.post("/api/usuarios")
def nuevo_usuario(datos: NuevoUsuario):
    try:
        return casos.crear_usuario(datos.nombre)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/casos")
def listar_casos(usuario: int, archivados: bool = False):
    return casos.listar_casos(usuario, archivados)


@app.post("/api/casos")
def nuevo_caso(datos: DatosCaso):
    if not casos.usuario(datos.usuario_id):
        raise HTTPException(400, "Usuario desconocido.")
    return casos.crear_caso(datos.usuario_id, datos.model_dump(exclude={"usuario_id"}))


def _guardadas_con_fichas(caso_id: int) -> list[dict]:
    salida = []
    for g in casos.guardadas(caso_id):
        pid = busqueda.id_por_radicado(g["corte_clave"], g["radicado"])
        ficha = busqueda.ficha(pid) if pid else None
        salida.append({**g, "id": pid, "ficha": ficha})
    return salida


@app.get("/api/casos/{caso_id}")
def ver_caso(caso_id: int):
    caso = _caso_o_404(caso_id)
    lista = casos.analisis_del_caso(caso_id)
    ultimo = next((a for a in lista if a["estado"] != "error"), lista[0] if lista else None)
    return {
        "caso": caso,
        "usuario": casos.usuario(caso["usuario_id"]),
        "guardadas": _guardadas_con_fichas(caso_id),
        "analisis": lista,
        "ultimo": precedentes.con_ids(casos.obtener_analisis(ultimo["id"])) if ultimo else None,
        "historial": casos.historial(caso_id),
    }


@app.put("/api/casos/{caso_id}")
def editar_caso(caso_id: int, datos: DatosCaso):
    _caso_o_404(caso_id)
    return casos.actualizar_caso(caso_id, datos.usuario_id, datos.model_dump(exclude={"usuario_id"}, exclude_none=True))


@app.delete("/api/casos/{caso_id}")
def borrar_caso(caso_id: int):
    _caso_o_404(caso_id)
    casos.eliminar_caso(caso_id)
    return {"ok": True}


@app.post("/api/casos/{caso_id}/analizar")
def analizar(caso_id: int, datos: Analizar):
    _caso_o_404(caso_id)
    try:
        return {"analisis_id": precedentes.iniciar(caso_id, datos.usuario_id, datos.amplitud)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/analisis/{analisis_id}")
def ver_analisis(analisis_id: int):
    a = casos.obtener_analisis(analisis_id)
    if not a:
        raise HTTPException(404, "No existe ese análisis.")
    return precedentes.con_ids(a)


@app.put("/api/casos/{caso_id}/guardadas")
def guardar(caso_id: int, datos: Guardar):
    _caso_o_404(caso_id)
    if datos.estado not in ("precedente", "descartada"):
        raise HTTPException(400, "Estado no válido.")
    casos.guardar_sentencia(caso_id, datos.usuario_id, datos.corte_clave, datos.radicado, datos.estado, datos.nota, datos.datos)
    return {"ok": True, "guardadas": _guardadas_con_fichas(caso_id)}


@app.delete("/api/casos/{caso_id}/guardadas")
def quitar(caso_id: int, usuario_id: int, corte_clave: str, radicado: str):
    _caso_o_404(caso_id)
    casos.quitar_sentencia(caso_id, usuario_id, corte_clave, radicado)
    return {"ok": True, "guardadas": _guardadas_con_fichas(caso_id)}


@app.get("/api/casos/{caso_id}/informe")
def informe(caso_id: int):
    caso = _caso_o_404(caso_id)
    texto = informes.informe_md(caso, _guardadas_con_fichas(caso_id), casos.analisis_del_caso(caso_id))
    nombre = re.sub(r"[^\w\-]+", "_", caso["titulo"])[:60] or "caso"
    return PlainTextResponse(texto, media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{nombre}.md"'})


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

    casos.marcar_interrumpidos()
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
