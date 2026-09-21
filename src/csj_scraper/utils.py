from __future__ import annotations

import re
import unicodedata


def slugify(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    texto = texto.lower().strip()
    texto = re.sub(r"[^a-z0-9]+", "-", texto)
    return texto.strip("-") or "sin-nombre"


def radicado_desde_titulo(title: str) -> str:
    """'SL208-2026.pdf' -> 'SL208-2026'"""
    return re.sub(r"\.(pdf|docx?|rtf)$", "", title.strip(), flags=re.IGNORECASE)


def extension_desde_titulo(title: str) -> str:
    match = re.search(r"\.([a-zA-Z0-9]+)$", title.strip())
    return match.group(1).lower() if match else "pdf"
