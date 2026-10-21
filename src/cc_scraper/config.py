"""Configuración del descargador de la Corte Constitucional (Relatoría).

Los datos se guardan en un repositorio aparte (Descargador-Sentencias-CC),
clonado junto a este, en la rama `datos`.
"""

import os
from pathlib import Path

from csj_scraper.config import PROJECT_ROOT

BUSCADOR_INDEX = "https://www.corteconstitucional.gov.co/relatoria/buscador_new/index.php"

# El WAF del sitio rechaza (HTTP 500) user-agents que no empiecen por un token
# de navegador o que contengan "CCBot" (ver README del repo de la CC).
USER_AGENT = "Mozilla/5.0 (compatible; DescargadorJurisprudencia/0.1; investigacion academica; contacto: cz122402@gmail.com)"

REQUEST_DELAY_SECONDS = 1.5
MAX_RETRIES = 5
BACKOFF_BASE_SECONDS = 2
TIMEOUT_SECONDS = 120

# Etiquetas exactas de la faceta prov_tipo del buscador -> prefijo corto.
TIPOS = {
    "T": "Tutela",
    "C": "Constitucionalidad",
    "SU": "Sentencia de unificación",
    "A": "Auto",
}
# Los autos no se descargan salvo que se pidan con --tipo A (decisión del
# usuario: no son relevantes para la búsqueda de jurisprudencia).
TIPOS_POR_DEFECTO = ["T", "C", "SU"]
MAX_CANT_PROVIDENCIAS = 5000
ANIO_INICIAL = 1992

# Página genérica que devuelve el sitio para providencias no publicadas.
TAMANO_MAXIMO_PAGINA_VACIA = 20_000

CORTE = "Corte Constitucional"
CORTE_DIR_NAME = "corte-constitucional"
DESTINO = Path(os.environ.get("CC_DATOS_DIR", PROJECT_ROOT.parent / "descargador-sentencias-cc"))
OUTPUT_ROOT = DESTINO / "jurisprudencia"
DB_PATH = OUTPUT_ROOT / "indice.sqlite"
ENUMERACION_DIR = DESTINO / "estado_enumeracion"
