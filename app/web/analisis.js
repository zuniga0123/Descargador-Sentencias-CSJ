"use strict";
// Vista del análisis de un caso con IA (versión 2): temas jurídicos con
// argumentos y sentencias evaluadas con fichas neutras y citas verificadas.
// Usa utilidades de app.js y casos.js.

let filtroCuestion = "";

const UTILIDAD = { a_favor: "A favor de su parte", en_contra: "En contra de su parte", mixta: "Mixta", ninguna: "" };
const UTILIDAD_NEUTRAL = { a_favor: "Útil", en_contra: "Desfavorable", mixta: "Sirve a ambas partes", ninguna: "" };
const FAVORECE = { trabajador: "la parte trabajadora", empleador: "la parte empleadora", accionante: "el accionante",
                   accionado: "el accionado", parcial: "ambas partes en parte", no_aplica: "" };
const PAPEL = { ratio: "Ratio decidendi", reiteracion: "Reiteración", obiter: "Obiter dictum" };
const RELACION = { coincide: ["✓", "coincide"], difiere: ["≠", "difiere"], no_consta: ["?", "no consta"] };
const PARTE = { trabajador: "la parte trabajadora", empleador: "la parte empleadora" };

const idTarjeta = rad => "prec-" + String(rad).replace(/[^\w-]/g, "_");

function enlaceSentencia(rad, porRadicado) {
  const r = porRadicado.get(rad);
  return r ? `<a href="#" class="chip-sentencia ${r.corte_clave}" data-ir-tarjeta="${esc(rad)}" title="${esc(r.tipo || "")} ${esc(rad)} (${r.ano})">${esc(rad)}</a>`
           : `<span class="chip-sentencia">${esc(rad)}</span>`;
}

// Convierte [RADICADO] en enlaces y resalta las citas marcadas como no verificadas.
function conCitas(texto, porRadicado) {
  return esc(texto || "")
    .replace(/\[([^\[\]]{3,40}?) — no está entre[^\]]*\]/g, (m, rad) =>
      `<span class="cita-dudosa" title="La IA citó una sentencia que no está entre los precedentes revisados para este tema. Verifíquela antes de usarla.">[${rad} ⚠ no verificada]</span>`)
    .replace(/\[([^\[\]]{3,40})\]/g, (m, rad) => porRadicado.has(rad) ? `[${enlaceSentencia(rad, porRadicado)}]` : m);
}

function htmlAnalisisV2(a) {
  const plan = a.planteamiento;
  const posicion = plan.posicion || "neutral";
  window.terminosLector = (plan.terminos_clave || []).slice(0, 12).map(t => `"${t}"`).join(" ");
  const porRadicado = new Map(a.resultados.map(r => [r.radicado, r]));
  const guardadas = new Map(casoActual.guardadas.map(g => [clave(g.corte_clave, g.radicado), g.estado]));
  const visibles = a.resultados.filter(r => guardadas.get(clave(r.corte_clave, r.radicado)) !== "descartada");
  const enFiltro = visibles.filter(r => !filtroCuestion || r.cuestiones.includes(filtroCuestion));
  const fuertes = enFiltro.filter(r => r.pertinencia >= 40);
  const debiles = enFiltro.filter(r => r.pertinencia < 40);
  const hechos = plan.hechos_relevantes || [];

  const cuestiones = plan.cuestiones.map((c, i) => {
    const an = c.analisis || {};
    const argumentos = (an.argumentos || []).map((x, j) => `
      <li class="argumento">
        <p class="tesis">${esc(x.tesis)}</p>
        ${x.desarrollo ? `<p>${conCitas(x.desarrollo, porRadicado)}</p>` : ""}
        <p class="apoyo">${x.apoyo.length ? "Apoyo: " + x.apoyo.map(rad => enlaceSentencia(rad, porRadicado)).join(" ") : `<span class="meta">Sin precedente en la base que lo respalde</span>`}
          ${x.apoyo_no_verificado?.length ? `<span class="cita-dudosa" title="La IA las citó pero no están entre los precedentes revisados para este tema">⚠ también citó ${x.apoyo_no_verificado.map(esc).join(", ")}: no verificadas</span>` : ""}</p>
        ${x.objecion ? `<p class="objecion"><b>Objeción previsible:</b> ${conCitas(x.objecion, porRadicado)}</p>` : ""}
        ${(x.revision || []).map(rv => `<p class="revision ${rv.gravedad}"><b>⚠ Revisión crítica${rv.gravedad === "alta" ? " (importante)" : ""}:</b> ${esc(rv.problema)}</p>`).join("")}
      </li>`).join("");
    const contraparte = (an.contraparte || []).map(x => `<li>${esc(x.tesis)} ${x.apoyo.map(rad => enlaceSentencia(rad, porRadicado)).join(" ")}</li>`).join("");
    return `<details class="cuestion" ${i === 0 ? "open" : ""}>
      <summary><span class="id-cuestion">${c.id}</span> ${esc(c.cuestion)}
        <span class="meta">· ${c.precedentes.length} precedente${c.precedentes.length === 1 ? "" : "s"}</span></summary>
      <div class="cuestion-cuerpo">
        ${c.por_que ? `<p class="meta">${esc(c.por_que)}</p>` : ""}
        ${an.incompleto ? `<p class="revision">La respuesta de la IA para este tema llegó incompleta y se rescató lo que se pudo. Vuelva a buscar si falta algo.</p>` : ""}
        <h4>Qué dice la jurisprudencia encontrada</h4>
        <p class="estado-jurisprudencia">${conCitas(an.estado, porRadicado)}</p>
        ${argumentos ? `<h4>Argumentos ${posicion === "neutral" ? "de la parte trabajadora" : "para " + PARTE[posicion]}</h4><ol class="argumentos">${argumentos}</ol>` : ""}
        ${contraparte ? `<h4>${posicion === "neutral" ? "Argumentos de la parte empleadora" : "Lo que alegará la contraparte"}</h4><ul>${contraparte}</ul>` : ""}
        ${(an.por_verificar || []).length ? `<h4>Por verificar en el expediente</h4><ul class="por-verificar">${an.por_verificar.map(v => `<li>${esc(v)}</li>`).join("")}</ul>` : ""}
        ${an.vacios ? `<p class="vacios"><b>Vacíos:</b> ${esc(an.vacios)}</p>` : ""}
        ${c.precedentes.length ? `<p class="apoyo">Precedentes de este tema: ${c.precedentes.map(rad => enlaceSentencia(rad, porRadicado)).join(" ")}
          <button type="button" class="enlace" data-filtro-cuestion="${c.id}">ver sus fichas</button></p>` : ""}
      </div>
    </details>`;
  }).join("");

  const filtros = `<div class="filtro-cuestiones">
    <button type="button" data-filtro-cuestion="" ${!filtroCuestion ? 'aria-pressed="true"' : ""}>Todas (${visibles.length})</button>
    ${plan.cuestiones.map(c => `<button type="button" data-filtro-cuestion="${c.id}" ${filtroCuestion === c.id ? 'aria-pressed="true"' : ""} title="${esc(c.cuestion)}">${c.id} (${visibles.filter(r => r.cuestiones.includes(c.id)).length})</button>`).join("")}
  </div>`;

  return `
    <div class="planteamiento">
      <h3>Problema jurídico</h3><p>${esc(plan.problema_juridico)}</p>
      ${hechos.length ? `<p><b>Hechos determinantes:</b></p><ol class="hechos-caso">${hechos.map(h => `<li>${esc(h)}</li>`).join("")}</ol>` : ""}
      ${(plan.hechos_por_precisar || []).length ? `<div class="por-precisar"><b>Conviene precisar en la descripción del caso:</b>
        <ul>${plan.hechos_por_precisar.map(h => `<li>${esc(h)}</li>`).join("")}</ul></div>` : ""}
      <details><summary>Búsquedas que hizo${(plan.consultas_fallidas || []).length ? ` <span class="cita-dudosa">⚠ ${plan.consultas_fallidas.length} no se pudieron ejecutar</span>` : ""}</summary><ul class="consultas">${(plan.consultas || []).map(c =>
        `<li><a href="?q=${encodeURIComponent(c.consulta)}" target="_blank" rel="noopener"><code>${esc(c.consulta)}</code></a> ${c.proposito ? `<span class="meta">— ${esc(c.proposito)}</span>` : ""}
         ${(plan.consultas_fallidas || []).includes(c.consulta) ? `<span class="cita-dudosa">⚠ no se pudo ejecutar</span>` : ""}</li>`).join("")}</ul></details>
    </div>
    ${(plan.observaciones_generales || []).length ? `<div class="revision-general"><b>Revisión crítica de la estrategia:</b><ul>${plan.observaciones_generales.map(o => `<li>${esc(o)}</li>`).join("")}</ul></div>` : ""}
    ${(plan.errores || []).length ? `<div class="error-analisis">Algunas partes no se completaron: ${plan.errores.map(esc).join(" · ")}</div>` : ""}
    <h3 class="titulo-seccion">Temas jurídicos a resolver</h3>
    <p class="meta">Generado con IA: el estado de la jurisprudencia y los argumentos son un punto de partida. Antes de citar, abra cada sentencia (las citas textuales verificadas llevan ✓).</p>
    <div class="cuestiones">${cuestiones}</div>
    <h3 class="titulo-seccion" id="sentencias-evaluadas">Sentencias evaluadas</h3>
    <p class="meta">${num(a.resultados.length)} leídas por la IA sin conocer el caso y luego comparadas con él · ${fechaHora(a.creado)}${a.tokens_entrada ? ` · ${num(a.tokens_entrada + a.tokens_salida)} tokens` : ""}${casoActual.caso.recientes === 0 ? "" : " · con prioridad a las recientes"}</p>
    ${filtros}
    <ol class="lista-precedentes">${fuertes.map(r => htmlFichaV2(r, guardadas, hechos, posicion)).join("") || `<li class="vacio">Ninguna sentencia de este grupo resultó pertinente.</li>`}</ol>
    ${debiles.length ? `<details class="menos"><summary>Menos pertinentes (${debiles.length})</summary>
      <ol class="lista-precedentes">${debiles.map(r => htmlFichaV2(r, guardadas, hechos, posicion)).join("")}</ol></details>` : ""}`;
}

function citaHtml(texto, verificada, id) {
  if (!texto) return "";
  return `<blockquote class="cita-textual ${verificada ? "verificada" : "no-verificada"}">«${esc(texto)}»
    <span class="sello">${verificada ? "✓ Cita verificada en el texto" : "⚠ No se encontró literalmente en la sentencia: no la use sin revisar"}</span>
    ${verificada && id ? `<a href="#" data-cita-id="${id}" data-cita="${esc(texto)}">ver en el texto</a>` : ""}</blockquote>`;
}

function htmlFichaV2(r, guardadas, hechosCaso, posicion) {
  const f = r.ficha, comp = r.comparacion, res = f.resultado;
  const estadoG = guardadas.get(clave(r.corte_clave, r.radicado));
  const nivel = r.pertinencia >= 80 ? "alto" : r.pertinencia >= 60 ? "medio" : r.pertinencia >= 40 ? "bajo" : "minimo";
  const etiquetaUtil = (posicion === "neutral" ? UTILIDAD_NEUTRAL : UTILIDAD)[comp.utilidad];
  const ratio = f.reglas.filter(x => x.papel === "ratio");
  const datos = esc(JSON.stringify({
    corte_clave: r.corte_clave, radicado: r.radicado, decision: res.efecto,
    regla: (ratio.length ? ratio : f.reglas).map(x => x.regla).join(" "),
    cita: (ratio.find(x => x.verificada) || {}).cita || "", por_que: comp.explicacion_utilidad,
    puntaje: r.pertinencia, sentido: comp.utilidad === "a_favor" ? "favorable" : comp.utilidad === "en_contra" ? "desfavorable" : comp.utilidad === "mixta" ? "mixto" : "no_aplica",
  }));
  const matriz = comp.hechos.map(h => {
    const n = parseInt(String(h.h).replace(/\D/g, ""), 10);
    const [simbolo, nombre] = RELACION[h.relacion] || RELACION.no_consta;
    return `<li class="rel-${h.relacion}" title="${nombre}"><span class="simbolo">${simbolo}</span>
      <span>${esc(hechosCaso[n - 1] || h.h)}${h.detalle ? ` <span class="meta">— ${esc(h.detalle)}</span>` : ""}</span></li>`;
  }).join("");
  return `<li class="precedente ficha-v2 ${r.corte_clave} ${estadoG === "precedente" ? "guardado" : ""}" id="${idTarjeta(r.radicado)}">
    <div class="puntaje ${nivel}" title="Pertinencia para el caso, de 0 a 100">${r.pertinencia}</div>
    <div class="precedente-cuerpo">
      <h4>${r.id ? `<a href="#" data-ver="${r.id}">${esc(r.tipo || "")} ${esc(r.radicado)}</a>` : esc(r.radicado)}
        ${etiquetaUtil ? `<span class="etiqueta util-${comp.utilidad}">${etiquetaUtil}</span>` : ""}
        ${f.decide_fondo ? `<span class="etiqueta fondo">Decide el fondo</span>` : `<span class="etiqueta forma" title="${esc(f.motivo_si_no_decide_fondo)}">No decide el fondo</span>`}
        <span class="etiqueta" title="Calculado por la app: hechos del caso que coinciden con los de la sentencia">Hechos ${r.similitud_hechos}/10</span>
        ${r.cuestiones.map(c => `<span class="etiqueta">${c}</span>`).join("")}
      </h4>
      <div class="meta">${esc(NOMBRE_CORTE_CORTO[r.corte_clave] || r.corte)} · ${esc(r.sala || "")} · ${esc(fechaLarga(r.fecha, r.ano))}${r.ponente ? " · M.P. " + esc(r.ponente) : ""}</div>
      <p class="resultado"><b>Resultado:</b> ${esc(res.efecto)}${FAVORECE[res.favorece_a] ? ` <span class="meta">(favoreció a ${FAVORECE[res.favorece_a]})</span>` : ""}
        ${!f.decide_fondo && f.motivo_si_no_decide_fondo ? `<br><span class="meta">No decidió el fondo: ${esc(f.motivo_si_no_decide_fondo)}</span>` : ""}</p>
      ${citaHtml(res.cita, res.verificada, r.id)}
      ${f.reglas.map(x => `<div class="regla ${x.papel}"><span class="papel">${PAPEL[x.papel]}</span> ${esc(x.regla)}${citaHtml(x.cita, x.verificada, r.id)}</div>`).join("")}
      <div class="frente-al-caso">
        ${comp.analogias ? `<p class="analogia"><b>Se parece especialmente:</b> ${esc(comp.analogias)}</p>` : ""}
        ${comp.diferencias ? `<p><b>Diferencias:</b> ${esc(comp.diferencias)}</p>` : ""}
        ${comp.explicacion_utilidad ? `<p><b>Utilidad:</b> ${esc(comp.explicacion_utilidad)}</p>` : ""}
        ${matriz ? `<details><summary>Comparación hecho por hecho</summary><ul class="matriz-hechos">${matriz}</ul></details>` : ""}
        ${f.hechos.length ? `<details><summary>Hechos de la sentencia (ficha neutra)</summary><ul>${f.hechos.map(h => `<li>${esc(h)}</li>`).join("")}</ul>
          ${f.problema_juridico ? `<p><b>Problema jurídico que resolvió:</b> ${esc(f.problema_juridico)}</p>` : ""}</details>` : ""}
      </div>
      <div class="acciones-precedente">
        ${r.id ? `<button type="button" data-ver="${r.id}">Ver sentencia</button>` : ""}
        ${estadoG === "precedente"
          ? `<button type="button" class="guardada" data-quitar="${datos}">★ Guardada</button>`
          : `<button type="button" class="primario" data-guardar="${datos}">☆ Guardar en el caso</button>`}
        <button type="button" class="enlace" data-descartar="${datos}" title="No volverá a aparecer en las búsquedas de este caso">No sirve</button>
      </div>
    </div>
  </li>`;
}

function conectarAccionesV2(caja) {
  $$("[data-cita-id]", caja).forEach(a => a.onclick = ev => {
    ev.preventDefault();
    window.citaLector = a.dataset.cita;
    if (String(estado.ver) === a.dataset.citaId) irACita();
    else navegar({ ver: a.dataset.citaId });
  });
  $$("[data-filtro-cuestion]", caja).forEach(b => b.onclick = () => {
    filtroCuestion = b.dataset.filtroCuestion;
    pintarPestanas();
    document.getElementById("sentencias-evaluadas")?.scrollIntoView({ behavior: "smooth" });
  });
  $$("[data-ir-tarjeta]", caja).forEach(a => a.onclick = ev => {
    ev.preventDefault();
    let destino = document.getElementById(idTarjeta(a.dataset.irTarjeta));
    if (!destino && filtroCuestion) { filtroCuestion = ""; pintarPestanas(); destino = document.getElementById(idTarjeta(a.dataset.irTarjeta)); }
    if (destino) {
      destino.closest("details.menos")?.setAttribute("open", "");
      destino.scrollIntoView({ behavior: "smooth", block: "start" });
      destino.classList.add("destacada");
      setTimeout(() => destino.classList.remove("destacada"), 1800);
    }
  });
}
