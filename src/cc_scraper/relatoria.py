"""Consultas al buscador de la Relatoría de la Corte Constitucional.

Endpoints (descubiertos en el proyecto anterior, Descargador-Sentencias-CC):
- searchByAggs: lista por faceta tipo + año; una sola solicitud trae hasta
  5000 resultados. El WAF bloquea repetir un mismo campo de faceta, por eso
  se consulta una combinación (tipo, año) a la vez.
- ver_titulacionesXIDprovidencia: temas (descriptor) / subtemas (restrictor)
  oficiales de la Relatoría.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from markdownify import markdownify

from . import config
from .cliente import CcClient


@dataclass
class ResultadoBusqueda:
    radicado: str
    numero: str
    url: str
    prov_id: str | None
    tipo: str
    fecha_sentencia: str | None
    fecha_publicacion: str | None
    tema_relatoria: str | None
    resumen: str | None


@dataclass
class Documento:
    markdown: str
    magistrado_ponente: str | None
    normas: list[str] = field(default_factory=list)


def _tema_y_resumen(celda) -> tuple[str | None, str | None]:
    texto = celda.get_text(separator="\n", strip=True)
    if "TEMA:" not in texto:
        return None, None
    resto = texto.split("TEMA:", 1)[1]
    tema, _, resumen = resto.partition("RESUMEN:")
    return " ".join(tema.split()) or None, " ".join(resumen.split()) or None


def buscar_por_tipo_y_anio(client: CcClient, tipo: str, anio: int) -> list[ResultadoBusqueda]:
    data = {
        "searchOption": "texto",
        "buscar_por": "",
        "finicio": f"{config.ANIO_INICIAL}-01-01",
        "ffin": f"{anio}-12-31",
        "ver_formulario": "si",
        "volver_a": "relatoria",
        "OrderbyOption": "des__score",
        "cant_providencias": config.MAX_CANT_PROVIDENCIAS,
        "maxprov": config.MAX_CANT_PROVIDENCIAS,
        "accion": "searchByAggs",
        "aggs_prov_tipo[]": f"prov_tipo|{config.TIPOS[tipo]}|0",
        "aggs_prov_f_sentencia[]": f"prov_f_sentencia|{anio}|0",
    }
    resp = client.post(config.BUSCADOR_INDEX, data=data)
    tabla = BeautifulSoup(resp.text, "html.parser").find("table", id="tablet_results")
    if tabla is None or tabla.find("tbody") is None:
        return []
    resultados = []
    for fila in tabla.find("tbody").find_all("tr", recursive=False):
        celdas = fila.find_all("td", recursive=False)
        enlace = celdas[0].find("a", title="Ver providencia") if celdas else None
        if len(celdas) < 4 or enlace is None:
            continue
        url = enlace.get("href", "")
        oculto = celdas[0].find("input", attrs={"type": "hidden"})
        tema, resumen = _tema_y_resumen(celdas[2])
        resultados.append(
            ResultadoBusqueda(
                radicado=PurePosixPath(urlparse(url).path).stem,
                numero=enlace.get_text(strip=True),
                url=url,
                prov_id=oculto.get("value") if oculto else None,
                tipo=tipo,
                fecha_sentencia=celdas[1].get_text(strip=True) or None,
                fecha_publicacion=celdas[3].get_text(strip=True) or None,
                tema_relatoria=tema,
                resumen=resumen,
            )
        )
    return resultados


def obtener_titulaciones(client: CcClient, prov_id: str) -> list[dict[str, str | None]]:
    resp = client.post(config.BUSCADOR_INDEX, data={"prov_id": prov_id, "accion": "ver_titulacionesXIDprovidencia"})
    tabla = BeautifulSoup(resp.text, "html.parser").find("table", id="tablet_titulaciones")
    if tabla is None or tabla.find("tbody") is None:
        return []
    titulaciones = []
    for fila in tabla.find("tbody").find_all("tr", recursive=False):
        celdas = [c.get_text(" ", strip=True) for c in fila.find_all("td", recursive=False)]
        if len(celdas) >= 2 and celdas[0]:
            titulaciones.append({"tema": " ".join(celdas[0].split()), "subtema": " ".join(celdas[1].split()) or None})
    return titulaciones


_RE_ETIQUETA_PONENTE = re.compile(
    r"magistrad[oa]s?\s+(?:ponentes?|sustanciador[a]?)\s*(?:\([^)]*\))?\s*:?\s*", re.IGNORECASE
)
_CONECTORES = {"de", "del", "la", "las", "los", "y", "e", "DE", "DEL", "LA", "LAS", "LOS", "Y", "E"}
_NO_SON_NOMBRE = {
    "bogota", "bogotá", "santafe", "santafé", "santa", "aprobado", "aprobada", "referencia", "expediente",
    "acta", "sentencia", "auto", "demanda", "asunto", "actor", "actora", "accionante", "procedencia", "tema",
    "magistrado", "magistrada", "sala", "corte", "el", "la", "en", "con", "radicacion", "radicación",
}


_RE_FIRMA = re.compile(
    r"([A-ZÁÉÍÓÚÑÜ]{2,}(?:\s+(?:DE|DEL|LA|LOS|Y|[A-ZÁÉÍÓÚÑÜ]{2,})){1,5})\s+Magistrad[oa]\s+"
    r"(?:\(e\)\s+)?(?:Ponente|Sustanciador[a]?|Presidente)"
)


def _extraer_ponente_de_firma(texto: str) -> str | None:
    firmas = list(_RE_FIRMA.finditer(texto[-6000:]))
    return firmas[0].group(1).title() if firmas else None


def _extraer_ponente(texto: str) -> str | None:
    """Toma el nombre que sigue a "Magistrado Ponente:" (en mayúsculas o con
    mayúscula inicial) y corta antes de palabras que no forman parte del
    nombre ("Bogotá", "Aprobado según Acta", etc.)."""
    etiqueta = _RE_ETIQUETA_PONENTE.search(texto)
    if etiqueta is None:
        return None
    palabras = []
    for token in texto[etiqueta.end():etiqueta.end() + 120].split()[:8]:
        limpio = token.strip(".,;:()*\"'")
        if not limpio or limpio.lower() in _NO_SON_NOMBRE:
            break
        if limpio in _CONECTORES and palabras:
            palabras.append(limpio)
            continue
        if not limpio[0].isupper():
            break
        if palabras and palabras[0].isupper() and not limpio.isupper():
            break
        palabras.append(limpio)
        if token.rstrip().endswith((".", ",", ";")) and len(palabras) >= 2:
            break
    while palabras and palabras[-1] in _CONECTORES:
        palabras.pop()
    if len(palabras) < 2:
        return None
    nombre = " ".join(palabras)
    return nombre.title() if nombre.isupper() else nombre


_RE_NORMA = re.compile(r"\b(Ley|Decreto(?:\s+Ley)?|Acto\s+Legislativo)\s+(\d{1,4})\s+de\s+(\d{4})\b")


def _unir_lineas_partidas(markdown: str) -> str:
    bloques = []
    for bloque in re.split(r"\n\s*\n", markdown):
        if bloque.lstrip().startswith(("|", "-", "*   ", "1.")):
            bloques.append(bloque.strip())
        else:
            bloques.append(" ".join(bloque.split()))
    return "\n\n".join(b for b in bloques if b) + "\n"


def descargar_documento(client: CcClient, url: str) -> Documento | None:
    """Devuelve None si el sitio responde con su página genérica (providencia
    no publicada)."""
    resp = client.get(url)
    if len(resp.content) < config.TAMANO_MAXIMO_PAGINA_VACIA:
        texto_plano = BeautifulSoup(resp.content, "html.parser").get_text(" ")
        if len(" ".join(texto_plano.split())) < 200:
            return None
    charset = re.search(rb"charset=([\w-]+)", resp.content[:3000])
    try:
        html = resp.content.decode(charset.group(1).decode() if charset else "windows-1252", errors="replace")
    except LookupError:
        html = resp.content.decode("windows-1252", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    for etiqueta in soup(["script", "style", "head"]):
        etiqueta.decompose()
    markdown = _unir_lineas_partidas(markdownify(str(soup.body or soup), heading_style="ATX", bullets="-"))

    texto = " ".join(soup.get_text(" ").split())
    ponente = _extraer_ponente(texto[:8000]) or _extraer_ponente_de_firma(texto)
    normas = []
    for m in _RE_NORMA.finditer(texto):
        norma = f"{' '.join(m.group(1).split()).title()} {int(m.group(2))} de {m.group(3)}"
        if norma not in normas:
            normas.append(norma)
    return Documento(
        markdown=markdown,
        magistrado_ponente=ponente,
        normas=normas[:40],
    )
