from __future__ import annotations

import logging
import time

import requests

from . import config

logger = logging.getLogger(__name__)


class CcClient:
    """GET/POST al sitio de la Relatoría con pausa entre solicitudes y
    reintentos con backoff ante errores de red, 429 y 5xx."""

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": config.USER_AGENT, "Accept-Language": "es-CO,es;q=0.9"})
        self._ultimo = 0.0

    def _pedir(self, metodo: str, url: str, **kwargs) -> requests.Response:
        ultimo_error: Exception | None = None
        for intento in range(1, config.MAX_RETRIES + 1):
            espera = config.REQUEST_DELAY_SECONDS - (time.monotonic() - self._ultimo)
            if espera > 0:
                time.sleep(espera)
            try:
                resp = self.session.request(metodo, url, timeout=config.TIMEOUT_SECONDS, **kwargs)
                self._ultimo = time.monotonic()
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise requests.HTTPError(f"HTTP {resp.status_code}")
                resp.raise_for_status()
                return resp
            except requests.RequestException as exc:
                self._ultimo = time.monotonic()
                ultimo_error = exc
                if intento == config.MAX_RETRIES:
                    break
                backoff = config.BACKOFF_BASE_SECONDS * (2 ** (intento - 1))
                logger.warning("Intento %d/%d falló para %s (%s); reintentando en %ds", intento, config.MAX_RETRIES, url, exc, backoff)
                time.sleep(backoff)
        raise RuntimeError(f"Fallaron {config.MAX_RETRIES} intentos contra {url}") from ultimo_error

    def get(self, url: str, **kwargs) -> requests.Response:
        return self._pedir("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> requests.Response:
        return self._pedir("POST", url, **kwargs)
