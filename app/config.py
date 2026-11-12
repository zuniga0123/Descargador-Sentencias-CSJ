"""Rutas y fuentes de datos de la app de búsqueda de jurisprudencia."""

import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
# Carpeta de instalación: la que contiene app/. Ahí van datos/ y descargas/.
BASE_DIR = Path(os.environ.get("BUSCADOR_BASE_DIR", APP_DIR.parent))
DATOS_DIR = BASE_DIR / "datos"
DESCARGAS_DIR = BASE_DIR / "descargas"
DB_PATH = Path(os.environ.get("BUSCADOR_DB", DATOS_DIR / "jurisprudencia.sqlite"))

# Fuentes públicas en GitHub (ZIP generado por GitHub para cada rama).
FUENTES = {
    "csj": {
        "nombre": "Corte Suprema de Justicia - Sala Laboral",
        "zip_url": "https://codeload.github.com/zuniga0123/Descargador-Sentencias-CSJ/zip/refs/heads/claude/csj-colombia-sentencias-app-7eisz7",
        "zip_nombre": "csj.zip",
        "carpeta": "jurisprudencia/corte-suprema-sala-laboral/",
    },
    "cc": {
        "nombre": "Corte Constitucional",
        "zip_url": "https://codeload.github.com/zuniga0123/Descargador-Sentencias-CC/zip/refs/heads/datos",
        "zip_nombre": "cc.zip",
        "carpeta": "jurisprudencia/corte-constitucional/",
    },
}

HOST = "127.0.0.1"
PUERTO = 8000
RESULTADOS_POR_PAGINA = 20
