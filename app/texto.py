"""Limpieza y presentación del texto de las sentencias (compartido por el
lector y el buscador de precedentes)."""

from __future__ import annotations

import re

import markdown

# Párrafos cortos que en la práctica son títulos de sección aunque la fuente
# no los marque como tales (frecuente en la Corte Constitucional).
_PALABRAS_SECCION = (
    "ANTECEDENTES|HECHOS|LA DEMANDA|CONTESTACI[OÓ]N|PRETENSIONES|PRUEBAS|"
    "CONSIDERACIONES|FUNDAMENTOS|PROBLEMA JUR[IÍ]DICO|COMPETENCIA|DECISI[OÓ]N|RESUELVE|"
    "S[IÍ]NTESIS|CASO CONCRETO|EL CASO|SALVAMENTO DE VOTO|ACLARACI[OÓ]N DE VOTO|"
    "INTERVENCIONES|CONCEPTO DEL PROCURADOR|NORMA DEMANDADA|TEXTO DE LA NORMA|"
    "SENTENCIA (?:DE PRIMERA|DE SEGUNDA|IMPUGNADA|RECURRIDA)|EL RECURSO|LA OPOSICI[OÓ]N|"
    "CARGO|ACTUACI[OÓ]N|TR[AÁ]MITE|DECISIONES? (?:JUDICIALES|DE INSTANCIA)|ALCANCE DE LA IMPUGNACI[OÓ]N|"
    "DEMANDA DE CASACI[OÓ]N|ASUNTO|REFERENCIA"
)
_RE_TITULO = re.compile(
    r"^(?:\*\*)?\s*(?:(?:[IVXL]{1,6}|\d{1,2}|[A-H])[\.\-\)]\s*)?(?:" + _PALABRAS_SECCION + r")\b[^\n]{0,80}$",
    re.I,
)
_RE_MAYUS = re.compile(r"^(?:\*\*)?\s*(?:[IVXL]{1,6}[\.\-]\s+)[A-ZÁÉÍÓÚÑ ,\.:;\-]{4,90}(?:\*\*)?$")


_RE_ESPECIAL = re.compile(r"^(?:#|\||>|[-*+]\s|\d{1,3}[.)]\s|[IVXL]{1,6}[.)]\s)")
_FIN_ORACION = tuple(".:;?!»\"”)")


def _clave_linea(linea: str) -> str:
    return re.sub(r"\d+\s*$", "#", linea.strip())


def reflujo_pdf(texto: str) -> str:
    """Las sentencias de la Corte Suprema vienen de PDF: cada renglón quedó
    como párrafo y se intercalan encabezados de página. Aquí se quitan esos
    encabezados repetidos y se unen los renglones de un mismo párrafo."""
    from collections import Counter

    # Código de formato de la Corte que aparece en cada página (p. ej. "SCLAJPT-10 V.00 3").
    texto = re.sub(r"\bSCLA[A-Z]*-\d+\s+V\.\d+(?:\s+\d{1,3})?\b", " ", texto)
    bloques = [b.strip() for b in texto.split("\n\n")]
    cortos = Counter(_clave_linea(b) for b in bloques if b and len(b) < 70 and "\n" not in b)
    repetidos = {k for k, n in cortos.items() if n >= 3 and not k.startswith("#") and len(k) > 2}
    salida: list[str] = []
    for b in bloques:
        if not b or _clave_linea(b) in repetidos or re.fullmatch(r"\d{1,3}", b):
            continue
        previo = salida[-1] if salida else ""
        es_mayus = lambda x: sum(c.isalpha() for c in x) >= 4 and x.upper() == x
        unir = (
            previo
            and "\n" not in previo
            and "\n" not in b
            and not _RE_ESPECIAL.match(previo)
            and not _RE_ESPECIAL.match(b)
            and not es_mayus(previo)
            and not (es_mayus(b) and len(b) < 90)
            and (not previo.endswith(_FIN_ORACION) or b[:1].islower())
        )
        if unir:
            salida[-1] = previo[:-1] + b if previo.endswith("-") and b[:1].islower() else previo + " " + b
        else:
            salida.append(b)
    return "\n\n".join(salida)


def marcar_secciones(texto: str) -> str:
    bloques = texto.split("\n\n")
    for i, bloque in enumerate(bloques):
        b = bloque.strip()
        if not b or b.startswith("#") or "\n" in b or len(b) > 110:
            continue
        limpio = re.sub(r"\*+|\s*\(\d+\)$", "", b).strip(" #").rstrip(":.")
        es_mayus = limpio.upper() == limpio and sum(c.isalpha() for c in limpio) >= 5
        if _RE_MAYUS.match(b) or (es_mayus and _RE_TITULO.match(limpio)):
            bloques[i] = "### " + limpio
    return "\n\n".join(bloques)


def a_html(texto: str) -> tuple[str, list[dict]]:
    md = markdown.Markdown(extensions=["tables", "toc", "sane_lists"], extension_configs={"toc": {"toc_depth": "2-5"}})
    # El texto viene de la fuente: se escapa cualquier HTML incrustado.
    html = md.convert(marcar_secciones(texto.replace("<", "&lt;")))
    indice: list[dict] = []

    def aplanar(tokens):
        for t in tokens:
            indice.append({"id": t["id"], "titulo": t["name"], "nivel": t["level"]})
            aplanar(t["children"])

    aplanar(md.toc_tokens)
    return html, indice
