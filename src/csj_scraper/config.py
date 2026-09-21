"""Configuración central del descargador de jurisprudencia laboral de la CSJ."""

from pathlib import Path

# --- Endpoints oficiales (descubiertos por ingeniería inversa del bundle.js
# de https://consultaprovidencias.cortesuprema.gov.co/, sept. 2026) ---
API_URL = "https://consultaprovidenciasbk.cortesuprema.gov.co/api"
DOWNLOAD_URL = "https://consultaprovidenciasbk.cortesuprema.gov.co/downloadFile"
FILE_EXISTS_URL = "https://consultaprovidenciasbk.cortesuprema.gov.co/fileExists"

USER_AGENT = (
    "DescargadorSentenciasCSJ/0.1 "
    "(uso academico/personal; contacto: cz122402@gmail.com)"
)

# Pausa entre solicitudes HTTP (segundos). Scraping respetuoso sobre un
# sitio oficial sin robots.txt declarado explícitamente.
REQUEST_DELAY_SECONDS = 1.5
MAX_RETRIES = 5
BACKOFF_BASE_SECONDS = 2

# Sala de Casación Laboral en el sistema de la CSJ. El campo "id" de cada
# resultado ya distingue la sub-sala en la ruta, p.ej.:
#   /Index/LABORAL/PERMANENTE/...      -> Sala de Casación Laboral
#   /Index/LABORAL/DESCONGESTION/...   -> Sala de Descongestión Laboral
SALA = "LABORAL"
SUB_SALAS = {
    "PERMANENTE": "sala-casacion-laboral",
    "DESCONGESTION": "sala-descongestion-laboral",
}
SUB_SALA_DESCONOCIDA = "sub-sala-sin-identificar"

TIPOS_PROVIDENCIA = ["SENTENCIA", "AUTO"]

# Término de búsqueda usado para enumerar (casi) todas las providencias de
# un año, dado que la API no ofrece un modo "traer todo" sin texto de
# búsqueda. "de" aparece en prácticamente cualquier providencia en español.
QUERY_COMODIN = "de"

RESULTS_PER_PAGE = 10

# Rango de años a cubrir (últimos 15 años, ver brief).
ANIOS_A_CUBRIR = 15

# --- Rutas de salida ---
PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = PROJECT_ROOT / "jurisprudencia"
CORTE_DIR_NAME = "corte-suprema-sala-laboral"
DB_PATH = PROJECT_ROOT / "jurisprudencia" / "indice.sqlite"
