"""Informe del caso en Markdown (para pegar en Word o pasarlo a otra IA)."""

from __future__ import annotations

import time

from . import casos

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]


def fecha_larga(fecha: str | None, ano: int | None = None) -> str:
    if not fecha:
        return str(ano or "s. f.")
    a, m, d = fecha.split("-")
    return f"{int(d)} de {MESES[int(m) - 1]} de {a}"


def cita(f: dict) -> str:
    fecha = fecha_larga(f.get("fecha"), f.get("ano"))
    ponente = f.get("ponente") or "—"
    if f.get("corte_clave") == "cc":
        partes = f["radicado"].split("-")
        nombre = f"{partes[0]}-{partes[1]} de {f.get('ano')}" if len(partes) == 3 else f["radicado"]
        return f"Corte Constitucional, Sentencia {nombre} ({fecha}), M.P. {ponente}."
    rad = f" (Radicación {f['radicacion']})" if f.get("radicacion") else ""
    return f"Corte Suprema de Justicia, {f.get('sala') or 'Sala Laboral'}, Sentencia {f['radicado']}{rad}, {fecha}, M.P. {ponente}."


def informe_md(caso: dict, guardadas: list[dict], lista_analisis: list[dict]) -> str:
    usuario = casos.usuario(caso["usuario_id"]) or {}
    lineas = [
        f"# {caso['titulo']}",
        "",
        f"Informe generado el {time.strftime('%Y-%m-%d %H:%M')} · Responsable: {usuario.get('nombre', '—')}",
        "",
        "## Hechos y particularidades",
        "",
        caso["descripcion"].strip() or "—",
    ]
    if caso.get("pretensiones", "").strip():
        lineas += ["", "## Lo que se pide o se discute", "", caso["pretensiones"].strip()]

    ultimo = next((a for a in lista_analisis if a["estado"] == "listo"), None)
    analisis = casos.obtener_analisis(ultimo["id"]) if ultimo else None
    plan = (analisis or {}).get("planteamiento") or {}
    if plan.get("problema_juridico"):
        lineas += ["", "## Problema jurídico", "", plan["problema_juridico"]]
        if plan.get("asunto_de_fondo"):
            lineas += ["", f"**Asunto de fondo:** {plan['asunto_de_fondo']}"]
    if plan.get("sintesis"):
        lineas += ["", "## Síntesis de la jurisprudencia (generada con IA, verificar)", "", plan["sintesis"]]

    precedentes = [g for g in guardadas if g["estado"] == "precedente" and g.get("ficha")]
    lineas += ["", f"## Precedentes seleccionados ({len(precedentes)})", ""]
    if not precedentes:
        lineas.append("Aún no se han guardado precedentes en este caso.")
    for n, g in enumerate(precedentes, 1):
        d = g.get("datos") or {}
        lineas += [f"{n}. **{cita(g['ficha'])}**"]
        for etiqueta, clave in (("Decisión", "decision"), ("Regla aplicable", "regla"), ("Relación con el caso", "por_que")):
            if d.get(clave):
                lineas.append(f"   - {etiqueta}: {d[clave]}")
        if g.get("nota"):
            lineas.append(f"   - Nota: {g['nota']}")
        lineas.append("")

    if analisis:
        elegidas = {(g["corte_clave"], g["radicado"]) for g in guardadas}
        otras = [r for r in analisis.get("resultados") or []
                 if (r["corte_clave"], r["radicado"]) not in elegidas and r.get("puntaje", 0) >= 60][:10]
        if otras:
            lineas += ["## Otros precedentes sugeridos (sin revisar)", ""]
            for r in otras:
                extra = f" — {r['por_que']}" if r.get("por_que") else ""
                lineas.append(f"- {cita(r)} Puntaje {r['puntaje']}.{extra}")
            lineas.append("")
    lineas += ["---", "Las calificaciones y síntesis generadas con IA son orientativas: verifique cada sentencia antes de citarla."]
    return "\n".join(lineas) + "\n"
