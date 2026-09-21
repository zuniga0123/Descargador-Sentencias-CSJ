"""Convierte el HTML devuelto por getContentSearch (contentText) a Markdown
limpio, apto para que un agente de IA lo indexe/trocee.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup
from markdownify import markdownify as html_to_md


def clean_contenttext_to_markdown(content_text: str) -> str:
    """content_text trae <mark>...</mark> alrededor de coincidencias de
    búsqueda (ruido, no parte del texto original) y encabezados de sección
    envueltos en <div class="centered-title"><h2>...</h2></div>."""
    soup = BeautifulSoup(content_text, "html.parser")

    for mark in soup.find_all("mark"):
        mark.unwrap()

    for div in soup.find_all("div", class_="centered-title"):
        div.unwrap()

    markdown = html_to_md(str(soup), heading_style="ATX", bullets="-")

    # Colapsar saltos de línea/espacios excesivos que deja el HTML de origen.
    markdown = re.sub(r"[ \t]+\n", "\n", markdown)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    markdown = re.sub(r"[ \t]{2,}", " ", markdown)
    return markdown.strip() + "\n"
