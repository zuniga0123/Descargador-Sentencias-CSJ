"""Pasos de instalación/actualización que corren ya con Python disponible.

Lo llama `instalar_buscador.bat` (Windows). También sirve en Mac/Linux:
    python -m app.instalar
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys

from . import config, preparar_datos


def verificar_sqlite() -> None:
    try:
        sqlite3.connect(":memory:").execute("CREATE VIRTUAL TABLE t USING fts5(x)")
    except sqlite3.OperationalError:
        sys.exit(
            "Esta versión de Python no trae el buscador de texto de SQLite (FTS5).\n"
            "Instala Python 3.12 desde https://www.python.org/downloads/ y vuelve a ejecutar el instalador."
        )


def copiar_lanzadores() -> None:
    origen = config.APP_DIR / "windows"
    for nombre in ("iniciar.bat", "iniciar_en_red.bat", "actualizar.bat"):
        nuevo, actual = origen / nombre, config.BASE_DIR / nombre
        # Solo si cambió: así no se reescribe un .bat mientras se ejecuta.
        if nuevo.exists() and (not actual.exists() or actual.read_bytes() != nuevo.read_bytes()):
            shutil.copy2(nuevo, actual)


def crear_accesos_directos() -> None:
    if os.name != "nt":
        return
    destino = config.BASE_DIR / "iniciar.bat"
    script = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\\Buscador de Jurisprudencia.lnk');"
        f"$s.TargetPath='{destino}';$s.WorkingDirectory='{config.BASE_DIR}';"
        "$s.IconLocation='shell32.dll,22';$s.Save()"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True, capture_output=True, timeout=60)
        print("Acceso directo creado en el escritorio: 'Buscador de Jurisprudencia'.")
    except (OSError, subprocess.SubprocessError):
        print(f"No se pudo crear el acceso directo; abre el buscador con {destino}")


def main() -> None:
    verificar_sqlite()
    copiar_lanzadores()
    crear_accesos_directos()
    print("\nPreparando la base de búsqueda (la primera vez tarda unos 10 a 20 minutos)...\n")
    origenes = {}
    for clave in ("csj", "cc"):
        zip_local = config.DESCARGAS_DIR / config.FUENTES[clave]["zip_nombre"]
        if not zip_local.exists():
            preparar_datos.descargar(config.FUENTES[clave]["zip_url"], zip_local)
        origenes[clave] = zip_local
    try:
        preparar_datos.construir(origenes)
    except PermissionError:
        sys.exit("\nNo se pudo reemplazar la base: cierra la ventana del buscador y vuelve a ejecutar actualizar.bat.")
    for origen in origenes.values():
        origen.unlink(missing_ok=True)
    print("\nTodo listo. Abre el buscador con el acceso directo del escritorio o con iniciar.bat.")


if __name__ == "__main__":
    main()
