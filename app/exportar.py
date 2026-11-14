"""Exportación de la línea jurisprudencial a Word y Excel, con el mismo formato de la
skill de análisis jurisprudencial (López Medina):

- Linea_[tema].docx: apartados del paso 9 (problema, patrón fáctico, punto arquimédico,
  ingeniería reversa y nicho, gráfico como tabla, clasificación, evolución de subreglas,
  balance, vacíos) en tamaño carta, márgenes de 2,5 cm y Arial 11.
- Matriz_Linea_[tema].xlsx: hojas «Matriz», «Citas» y «Gráfico».
"""

from __future__ import annotations

import io
import re
import time

from . import citas, lineas

NOMBRE_CORTE = {"cc": "Corte Constitucional", "csj": "Corte Suprema de Justicia – Sala Laboral"}
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]


def _fecha(s: dict) -> str:
    f = s.get("fecha")
    if not f:
        return str(s.get("ano") or "")
    a, m, d = f.split("-")
    return f"{int(d)} de {MESES[int(m) - 1]} de {a}"


def _tema_breve(linea: dict) -> str:
    plan = linea["planteamiento"]
    base = plan.get("subtema") or plan.get("tema") or linea["titulo"]
    import unicodedata
    sin_tildes = "".join(c for c in unicodedata.normalize("NFD", base.lower()) if unicodedata.category(c) != "Mn")
    palabras = re.findall(r"[a-z0-9]+", sin_tildes)[:6]
    return "-".join(palabras) or f"linea-{linea['id']}"


def _votos(s: dict) -> str:
    partes = []
    for v in s.get("votos") or []:
        partes.append(f"{'Salvamento' if v['tipo'] == 'salvamento' else 'Aclaración'}{' parcial' if v.get('parcial') else ''}: {v['magistrado']}")
    return "; ".join(partes)


def _sin_marcas(texto: str) -> str:
    return re.sub(r"\[([^\[\]]+?) — no está en la línea: verifíquela\]", r"[\1 (no verificada)]", texto or "")


# ---------- Word ----------

def linea_docx(linea: dict) -> tuple[bytes, str]:
    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor

    plan, res = linea["planteamiento"], linea["resultado"] or {}
    sentencias = res.get("sentencias") or []
    doc = Document()
    seccion = doc.sections[0]
    seccion.page_width, seccion.page_height = Cm(21.59), Cm(27.94)
    for lado in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(seccion, lado, Cm(2.5))
    estilo = doc.styles["Normal"]
    estilo.font.name = "Arial"
    estilo.font.size = Pt(11)
    estilo.element.rPr.rFonts.set(qn("w:eastAsia"), "Arial")
    for nombre in ("Heading 1", "Heading 2", "Title"):
        st = doc.styles[nombre]
        st.font.name = "Arial"
        st.font.color.rgb = RGBColor(0x1F, 0x4E, 0x79)

    def sombrear(celda, color="D9E2F3"):
        tc = celda._tc.get_or_add_tcPr()
        sh = OxmlElement("w:shd")
        sh.set(qn("w:val"), "clear")
        sh.set(qn("w:color"), "auto")
        sh.set(qn("w:fill"), color)
        tc.append(sh)

    def tabla(encabezados, filas, anchos=None):
        t = doc.add_table(rows=1, cols=len(encabezados))
        t.style = "Table Grid"
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        for i, e in enumerate(encabezados):
            c = t.rows[0].cells[i]
            c.text = ""
            c.paragraphs[0].add_run(e).bold = True
            sombrear(c)
        for fila in filas:
            celdas = t.add_row().cells
            for i, v in enumerate(fila):
                celdas[i].text = str(v if v is not None else "")
        if anchos:
            for fila in t.rows:
                for i, w in enumerate(anchos):
                    fila.cells[i].width = Cm(w)
        for fila in t.rows:
            for c in fila.cells:
                for p in c.paragraphs:
                    for r in p.runs:
                        r.font.size = Pt(9.5)
        return t

    def transcripcion(texto, ubicacion, verificada):
        p = doc.add_paragraph()
        r = p.add_run(f"«{texto}»")
        r.italic = True
        p.add_run(f" ({ubicacion}{'' if verificada else '; cita NO verificada en el texto'})")

    def parrafo(etiqueta, texto):
        p = doc.add_paragraph()
        if etiqueta:
            p.add_run(f"{etiqueta}: ").bold = True
        p.add_run(texto or "—")

    titulo = doc.add_heading(f"Línea jurisprudencial. {linea['titulo']}", level=0)
    titulo.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph(f"Generada el {time.strftime('%Y-%m-%d')} con el Buscador de Jurisprudencia "
                      f"(base: Corte Constitucional 1992–2026; Corte Suprema, Sala Laboral 2009–2026). "
                      f"Las ubicaciones y clasificaciones hechas con IA son orientativas: cada una trae su cita, "
                      f"verificada contra el texto cuando se indica.").runs[0].font.size = Pt(9)

    doc.add_heading("1. Problema jurídico de la línea", level=1)
    tabla(["Problema jurídico", "Polo A", "Polo B"],
          [[plan.get("problema") or "—", plan.get("polo_a") or "—", plan.get("polo_b") or "—"]], [7.5, 4.3, 4.3])
    if plan.get("tema") or plan.get("subtema"):
        parrafo("Tema y subtema", f"{plan.get('tema') or '—'} / {plan.get('subtema') or '—'}")

    doc.add_heading("2. Escenario y patrón fáctico", level=1)
    doc.add_paragraph(plan.get("patron_factico") or "—")

    doc.add_heading("3. Punto arquimédico", level=1)
    for corte, rad in (plan.get("arquimedicas") or {}).items():
        razon = (plan.get("razon_arquimedica") or {}).get(corte)
        parrafo(NOMBRE_CORTE[corte], f"{rad}" + (f". {razon}" if razon else ""))

    doc.add_heading("4. Ingeniería reversa y nicho citacional", level=1)
    for corte in res.get("por_corte") or {}:
        propias = [s for s in sentencias if s["corte_clave"] == corte]
        doc.add_paragraph(NOMBRE_CORTE[corte]).runs[0].bold = True
        por_nivel: dict = {}
        for s in sentencias:
            if s.get("nivel") is not None:
                por_nivel.setdefault(s["nivel"], []).append(s["radicado"])
        for nivel in sorted(por_nivel):
            etiqueta = "Punto arquimédico" if nivel == 0 else f"Nivel {nivel} (citadas {'por el punto arquimédico' if nivel == 1 else 'por las del nivel anterior'})"
            parrafo(etiqueta, ", ".join(por_nivel[nivel]))
        nodales = sorted(propias, key=lambda s: -s["citada_en_linea"])[:6]
        parrafo("Puntos nodales (más citadas dentro de la línea)",
                ", ".join(f"{s['radicado']} ({s['citada_en_linea']})" for s in nodales if s["citada_en_linea"]) or "—")
        prospectivas = [s["radicado"] for s in propias if "prospectiva" in s["origen"]]
        if prospectivas:
            parrafo("Sentencias posteriores que la citan (búsqueda prospectiva)", ", ".join(prospectivas))
    if res.get("no_en_base"):
        parrafo("Citadas que no están en la base", ", ".join(f"{x['radicado']} ({x['veces']})" for x in res["no_en_base"][:20]))

    doc.add_heading("5. Gráfico de la línea", level=1)
    for corte in res.get("por_corte") or {}:
        ubicadas = [s for s in sentencias if s["corte_clave"] == corte and s.get("posicion")]
        if not ubicadas:
            continue
        doc.add_paragraph(NOMBRE_CORTE[corte]).runs[0].bold = True
        t = doc.add_table(rows=2, cols=7)
        t.style = "Table Grid"
        cab = ["Polo A", "1", "2", "3", "4", "5", "Polo B"]
        for i, e in enumerate(cab):
            t.rows[0].cells[i].text = ""
            t.rows[0].cells[i].paragraphs[0].add_run(e).bold = True
            sombrear(t.rows[0].cells[i])
        t.rows[1].cells[0].text = plan.get("polo_a") or ""
        t.rows[1].cells[6].text = plan.get("polo_b") or ""
        for s in ubicadas:
            celdas = t.add_row().cells
            marca = f"{s['radicado']} ({s.get('ano')})" + (" *" if s.get("clase") == "no_fija_linea" else "")
            celdas[s["posicion"]].text = marca
            if s.get("clase") in ("fundadora", "hito_consolidadora", "hito_modificadora", "hito_reconceptualizadora"):
                for r in celdas[s["posicion"]].paragraphs[0].runs:
                    r.bold = True
        for fila in t.rows:
            for i, c in enumerate(fila.cells):
                c.width = Cm(3.2 if i in (0, 6) else 1.9)
                for p in c.paragraphs:
                    for r in p.runs:
                        r.font.size = Pt(8.5)
        doc.add_paragraph("En negrilla, las sentencias fundadoras e hito; con *, las que no fijan línea.").runs[0].font.size = Pt(8.5)
    doc.add_paragraph("Justificación de cada ubicación:").runs[0].bold = True
    for s in sentencias:
        if not s.get("posicion"):
            continue
        p = doc.add_paragraph(style="List Bullet")
        p.add_run(f"{s['radicado']} — posición {s['posicion']}. ").bold = True
        p.add_run(s.get("justificacion") or "")
        if s.get("cita"):
            transcripcion(s["cita"], s.get("fundamento") or "ubicación no indicada", s.get("cita_verificada"))

    doc.add_heading("6. Clasificación de cada sentencia", level=1)
    tabla(["Sentencia", "Fecha", "Sala", "Clasificación", "Razón"],
          [[s["radicado"], _fecha(s), s["peso"]["etiqueta"], lineas.CLASES.get(s.get("clase") or "", "Sin clasificar"),
            s.get("razon_clase") or s.get("motivo_no_fija") or ""] for s in sentencias if s.get("posicion") or s.get("clase")],
          [2.6, 2.6, 3.2, 3.2, 4.6])

    doc.add_heading("7. Evolución de las subreglas", level=1)
    for corte, info in (res.get("por_corte") or {}).items():
        if info.get("evolucion"):
            parrafo(NOMBRE_CORTE[corte], _sin_marcas(info["evolucion"]))
    tabla(["Sentencia", "Subregla"], [[s["radicado"], s.get("subregla") or "—"] for s in sentencias if s.get("subregla")], [3, 13.2])

    doc.add_heading("8. Balance", level=1)
    for corte, info in (res.get("por_corte") or {}).items():
        doc.add_paragraph(NOMBRE_CORTE[corte]).runs[0].bold = True
        estado = info.get("estado") or {}
        parrafo("Estado de la línea", f"{estado.get('estado', '—')}. {estado.get('detalle', '')} Última sentencia: {info.get('ultima_sentencia') or '—'}.")
        parrafo("Doctrina vigente", _sin_marcas(info.get("doctrina_vigente") or "—"))
        parrafo("Sentencia dominante", info.get("dominante") or "—")
        if info.get("disidencias_recurrentes"):
            parrafo("Disidencias recurrentes", "; ".join(f"{d['magistrado']} ({d['salvamentos']} salvamentos)" for d in info["disidencias_recurrentes"]))
        for a in info.get("advertencias") or []:
            parrafo("Advertencia", a)
    if res.get("relacion"):
        parrafo("Relación entre las cortes", _sin_marcas(res["relacion"].get("relacion") or "—"))
        parrafo("Subregla de derecho", res["relacion"].get("subregla_de_derecho") or "—")
    if res.get("contactos"):
        doc.add_paragraph("Puntos de contacto entre las cortes:").runs[0].bold = True
        for x in res["contactos"][:15]:
            transcripcion(x["contexto"], f"{x['origen']}, al citar {x['destino']}{', nota al pie' if x.get('en_nota') else ''}", True)

    doc.add_heading("9. Vacíos", level=1)
    for corte, info in (res.get("por_corte") or {}).items():
        if info.get("vacios"):
            parrafo(NOMBRE_CORTE[corte], info["vacios"])
    doc.add_paragraph("La base no incluye las sentencias de tutela de la Sala Laboral (STL) ni autos; la Corte Suprema "
                      "está cubierta desde 2009. Una fundadora anterior puede no aparecer.")

    salida = io.BytesIO()
    doc.save(salida)
    return salida.getvalue(), f"Linea_{_tema_breve(linea)}.docx"


# ---------- Excel ----------

def linea_xlsx(linea: dict) -> tuple[bytes, str]:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    plan, res = linea["planteamiento"], linea["resultado"] or {}
    sentencias = res.get("sentencias") or []
    libro = Workbook()
    cabecera = PatternFill("solid", fgColor="D9E2F3")
    negrita = Font(bold=True)
    ajuste = Alignment(wrap_text=True, vertical="top")

    def formatear(hoja, anchos):
        for i, w in enumerate(anchos, 1):
            hoja.column_dimensions[get_column_letter(i)].width = w
        for celda in hoja[1]:
            celda.font = negrita
            celda.fill = cabecera
            celda.alignment = ajuste
        for fila in hoja.iter_rows(min_row=2):
            for celda in fila:
                celda.alignment = ajuste
        hoja.freeze_panes = "B2"

    matriz = libro.active
    matriz.title = "Matriz"
    matriz.append(["Número", "Fecha", "Corte", "Tipo", "Sala", "Peso de la fuente", "Ponente", "Patrón fáctico",
                   "Problema jurídico", "Decisión", "Subregla", "Posición (1 a 5)", "Clasificación en la línea",
                   "Fundamento", "Cita que sustenta la ubicación", "Cita verificada", "Salvamentos y aclaraciones",
                   "Origen en el nicho"])
    for s in sentencias:
        fi = s.get("ficha") or {}
        matriz.append([
            s["radicado"], s.get("fecha") or s.get("ano"), NOMBRE_CORTE[s["corte_clave"]], s.get("tipo"), s.get("sala"),
            s["peso"]["etiqueta"], s.get("ponente"), " | ".join(fi.get("hechos") or []), fi.get("problema_juridico"),
            (fi.get("resultado") or {}).get("efecto"), s.get("subregla"), s.get("posicion"),
            lineas.CLASES.get(s.get("clase") or "", "Sin clasificar" if s.get("posicion") else "No aborda el problema"),
            s.get("fundamento"), s.get("cita"), "sí" if s.get("cita_verificada") else "no", _votos(s),
            ", ".join(s.get("origen") or []),
        ])
    formatear(matriz, [14, 11, 18, 14, 18, 22, 22, 45, 40, 35, 45, 10, 20, 16, 50, 10, 30, 18])

    # Citas: doble entrada; al final, las citadas que no están en la línea (marcadas).
    hoja = libro.create_sheet("Citas")
    miembros = [s["radicado"] for s in sentencias]
    externas: dict[str, int] = {}
    menciones: dict[tuple[str, str], int] = {}
    for s in sentencias:
        for c in citas.citadas_por(s["corte_clave"], s["radicado"]):
            menciones[(s["radicado"], c["destino_radicado"])] = c["veces"]
            if c["destino_radicado"] not in miembros:
                externas[c["destino_radicado"]] = externas.get(c["destino_radicado"], 0) + 1
    extra = [r for r, n in sorted(externas.items(), key=lambda x: -x[1]) if n >= 2][:25]
    columnas = miembros + extra
    hoja.append(["Cita ↓ / Citada →"] + [c if c in miembros else f"{c} (fuera de la línea)" for c in columnas])
    for r in miembros:
        hoja.append([r] + [menciones.get((r, c)) or None for c in columnas])
    formatear(hoja, [16] + [11] * len(columnas))
    for i, c in enumerate(columnas, 2):
        if c not in miembros:
            hoja.cell(row=1, column=i).fill = PatternFill("solid", fgColor="FCE4D6")

    grafico = libro.create_sheet("Gráfico")
    grafico.append(["Corte", "Polo A", "1", "2", "3", "4", "5", "Polo B"])
    for corte in res.get("por_corte") or {}:
        ubicadas = [s for s in sentencias if s["corte_clave"] == corte and s.get("posicion")]
        if not ubicadas:
            continue
        grafico.append([NOMBRE_CORTE[corte], plan.get("polo_a"), None, None, None, None, None, plan.get("polo_b")])
        for s in ubicadas:
            fila = [None] * 8
            fila[0] = NOMBRE_CORTE[corte]
            fila[1 + s["posicion"]] = f"{s['radicado']} ({s.get('ano')})" + (" *" if s.get("clase") == "no_fija_linea" else "")
            grafico.append(fila)
    formatear(grafico, [24, 30, 16, 16, 16, 16, 16, 30])

    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue(), f"Matriz_Linea_{_tema_breve(linea)}.xlsx"
