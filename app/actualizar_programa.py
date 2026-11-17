"""Actualiza solo el programa (carpeta app/) desde GitHub, sin tocar la base de sentencias.

Consulta la lista de archivos de app/ en GitHub, compara cada uno con el que hay en este
computador (por su huella SHA-1 de git) y baja únicamente los que cambiaron. Después
instala las librerías nuevas, si las hay, y actualiza los .bat de la carpeta del buscador.
Toma menos de un minuto. Para traer sentencias nuevas se sigue usando actualizar.bat.

    python -m app.actualizar_programa
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = "zuniga0123/Descargador-Sentencias-CSJ"
RAMA = "claude/csj-colombia-sentencias-app-7eisz7"
API = "https://api.github.com/repos/" + REPO
CABECERAS = {"User-Agent": "BuscadorJurisprudencia-actualizador", "Accept": "application/vnd.github+json"}

APP = Path(__file__).resolve().parent
BASE = APP.parent


def _pedir(url: str, intentos: int = 3) -> bytes:
    ultimo = None
    for i in range(intentos):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=CABECERAS), timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 403 and "rate limit" in exc.read().decode("utf-8", "replace").lower():
                raise SystemExit("\nGitHub limitó las consultas desde esta red por una hora. Intente más tarde "
                                 "o use actualizar.bat.") from exc
            ultimo = exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            ultimo = exc
        time.sleep(3 * (i + 1))
    raise SystemExit(f"\nNo se pudo conectar con GitHub ({ultimo}). Revise la conexión a internet "
                     "(o el proxy de la oficina) e intente de nuevo.")


def huella_git(datos: bytes) -> str:
    """SHA-1 que usa git para un archivo ('blob')."""
    return hashlib.sha1(b"blob %d\0" % len(datos) + datos).hexdigest()


def listar_remoto(commit: str, ruta: str = "app") -> list[dict]:
    """Archivos de app/ en esa versión (recorre las subcarpetas). Se descargan por el
    identificador de la versión, no por el nombre de la rama: así nunca llega una copia vieja."""
    url = f"{API}/contents/{urllib.parse.quote(ruta)}?ref={commit}"
    archivos = []
    for item in json.loads(_pedir(url)):
        if item["type"] == "dir":
            archivos += listar_remoto(commit, item["path"])
        elif item["type"] == "file":
            archivos.append({"ruta": item["path"], "sha": item["sha"],
                             "url": f"https://raw.githubusercontent.com/{REPO}/{commit}/{urllib.parse.quote(item['path'])}"})
    return archivos


def version_remota() -> dict:
    datos = json.loads(_pedir(f"{API}/commits/{urllib.parse.quote(RAMA, safe='')}"))
    return {"sha": datos["sha"], "fecha": datos["commit"]["committer"]["date"][:10],
            "mensaje": datos["commit"]["message"].splitlines()[0]}


def main() -> None:
    print("Buscando la última versión del programa en GitHub…", flush=True)
    version = version_remota()
    remotos = listar_remoto(version["sha"])
    cambiar = []
    for a in remotos:
        local = BASE / a["ruta"]
        if not local.exists() or huella_git(local.read_bytes()) != a["sha"]:
            cambiar.append(a)
    if not cambiar:
        print(f"\nEl programa ya está al día (versión del {version['fecha']}).")
    else:
        print(f"Descargando {len(cambiar)} archivo(s)…", flush=True)
        # Primero se bajan todos; solo si todos llegaron bien se escriben.
        bajados = {}
        for a in cambiar:
            datos = _pedir(a["url"])
            if huella_git(datos) != a["sha"]:
                raise SystemExit(f"\nEl archivo {a['ruta']} llegó incompleto. Intente de nuevo; no se cambió nada.")
            bajados[a["ruta"]] = datos
        for ruta, datos in bajados.items():
            destino = BASE / ruta
            destino.parent.mkdir(parents=True, exist_ok=True)
            temporal = destino.with_name(destino.name + ".nuevo")
            temporal.write_bytes(datos)
            temporal.replace(destino)
            print(f"  ✓ {ruta}")
        for cache in APP.rglob("__pycache__"):
            shutil.rmtree(cache, ignore_errors=True)
        print(f"\nPrograma actualizado a la versión del {version['fecha']}: {version['mensaje']}")

    print("\nRevisando librerías…", flush=True)
    r = subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r",
                        str(APP / "requirements.txt")], capture_output=True, text=True)
    if r.returncode != 0:
        print("  No se pudieron instalar las librerías nuevas:\n" + (r.stderr or r.stdout)[-800:])
    else:
        print("  ✓ Librerías al día")

    # Los .bat de la carpeta del buscador (solo los que cambiaron) y el acceso directo.
    from . import instalar
    instalar.copiar_lanzadores()

    from . import config
    if not (config.DATOS_DIR / "citas.sqlite").exists():
        print("\nNota: para las líneas jurisprudenciales falta la red de citas. Prepárela desde la pestaña "
              "Líneas (unos 8 minutos, una sola vez).")
    print("\nListo. Abra el buscador de nuevo (si estaba abierto, ciérrelo y vuelva a abrirlo).")


if __name__ == "__main__":
    main()
