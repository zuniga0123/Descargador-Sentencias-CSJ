"""Cliente para la API GraphQL no documentada del buscador de providencias
de la Corte Suprema de Justicia (consultaprovidencias.cortesuprema.gov.co).

Esta API fue descubierta descompilando el bundle.js de la SPA oficial; no
hay documentación pública. Si en el futuro cambia de forma, este es el
único módulo que debería necesitar ajustes.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import requests

from . import config

logger = logging.getLogger(__name__)


class CsjApiError(RuntimeError):
    """Error irrecuperable al hablar con la API de la CSJ."""


def _escape_graphql_string(value: str) -> str:
    value = value.replace("\\", "\\\\")
    value = value.replace('"', '\\"')
    value = value.replace("\n", "\\n")
    return value


@dataclass
class SearchResult:
    title: str
    doc_id: str
    ano: int | None
    fecha_creacion: str | None
    tipo_providencia: str | None
    doctor: str | None
    leyes_o_articulos: list[str]


class CsjApiClient:
    """Envuelve getSearchResult, getContentSearch y /downloadFile con
    rate limiting y reintentos con backoff exponencial."""

    def __init__(
        self,
        delay_seconds: float = config.REQUEST_DELAY_SECONDS,
        max_retries: int = config.MAX_RETRIES,
    ) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": config.USER_AGENT,
                "Content-Type": "application/json",
            }
        )
        self.delay_seconds = delay_seconds
        self.max_retries = max_retries
        self._last_request_ts = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_ts
        wait = self.delay_seconds - elapsed
        if wait > 0:
            time.sleep(wait)

    def _post_with_retries(self, url: str, **kwargs) -> requests.Response:
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                resp = self.session.post(url, timeout=30, **kwargs)
                self._last_request_ts = time.monotonic()
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise CsjApiError(
                        f"HTTP {resp.status_code} de {url}: {resp.text[:200]}"
                    )
                resp.raise_for_status()
                return resp
            except (requests.RequestException, CsjApiError) as exc:
                last_exc = exc
                self._last_request_ts = time.monotonic()
                if attempt == self.max_retries:
                    break
                backoff = config.BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                logger.warning(
                    "Intento %d/%d falló para %s (%s); reintentando en %.1fs",
                    attempt,
                    self.max_retries,
                    url,
                    exc,
                    backoff,
                )
                time.sleep(backoff)
        raise CsjApiError(f"Fallaron {self.max_retries} intentos contra {url}") from last_exc

    def search(
        self,
        year: str,
        tipo_providencia: str,
        start: int = 0,
        query: str = config.QUERY_COMODIN,
        sala: str = config.SALA,
        magistrate: str = "",
        order: str = "NEW_FIRST",
        is_exact: bool = False,
    ) -> dict:
        q = _escape_graphql_string(query)
        gql = f"""
        {{
          getSearchResult(searchQuery:{{
            query: "{q}"
            typeOfQuery: "{sala}"
            start: {start}
            isExact: {"true" if is_exact else "false"}
            magistrate: "{_escape_graphql_string(magistrate)}"
            year: "{year}"
            autoSentencia: "{tipo_providencia}"
            order: "{order}"
            roomTutelas: ""
            addedQueries: []
          }}) {{
            searchResults {{
              title
              id
              ano
              fechaCreacion
              autoSentencia
              doctor
              leyesOArticulos
            }}
            numOfResults
          }}
        }}
        """
        resp = self._post_with_retries(config.API_URL, json={"query": gql})
        data = resp.json()
        if "errors" in data:
            raise CsjApiError(f"Errores GraphQL en search: {data['errors']}")
        return data["data"]["getSearchResult"]

    def get_full_content(self, doc_id: str, sala: str = config.SALA, text: str = config.QUERY_COMODIN) -> dict:
        gql = f"""
        {{
          getContentSearch(previewDocument:{{
            id: "{_escape_graphql_string(doc_id)}"
            room: "{sala}"
            text: "{_escape_graphql_string(text)}"
          }}) {{
            contentText
            title
            onlinePath
          }}
        }}
        """
        resp = self._post_with_retries(config.API_URL, json={"query": gql})
        data = resp.json()
        if "errors" in data:
            raise CsjApiError(f"Errores GraphQL en getContentSearch: {data['errors']}")
        return data["data"]["getContentSearch"]

    def download_file(self, path: str) -> tuple[bytes, str]:
        resp = self._post_with_retries(
            config.DOWNLOAD_URL,
            json={"path": path},
        )
        content_type = resp.headers.get("Content-Type", "application/octet-stream")
        return resp.content, content_type
