"use strict";
// Líneas jurisprudenciales: crear (por problema o por sentencia), ajustar el
// planteamiento, construir y ver el resultado con gráfico tiempo-posición.
// Usa utilidades de app.js y casos.js.

let lineaActual = null;
let sondeoLinea = null;
let filtroCorteLinea = "";
let editandoPlanteamiento = false;

const CLASES_LINEA = {
  fundadora: "Fundadora", hito_consolidadora: "Hito consolidadora", hito_modificadora: "Hito modificadora",
  hito_reconceptualizadora: "Hito reconceptualizadora", confirmadora: "Confirmadora", no_fija_linea: "No fija línea",
};
const ESTADOS_LINEA = { "pacífica": "estado-pacifica", "en tensión": "estado-tension", "cambio reciente": "estado-cambio", insuficiente: "" };
const NOMBRE_CORTE_LARGO = { cc: "Corte Constitucional", csj: "Corte Suprema – Sala Laboral" };
const USO_CITA = { fundamento: "la aplica como fundamento", reiteracion: "reitera su regla", mencion: "la menciona",
                   distincion: "la distingue", apartamiento: "se aparta de ella" };

function detenerSondeoLinea() { if (sondeoLinea) { clearInterval(sondeoLinea); sondeoLinea = null; } }

// ---------- Lista y creación ----------

async function pintarLineas() {
  const caja = $("#vista-lineas");
  const u = await asegurarUsuario();
  if (!u) return;
  caja.innerHTML = `<div class="pagina"><p class="meta">Cargando…</p></div>`;
  const [lista, red, ia_] = await Promise.all([api(`api/lineas?usuario=${u.id}`), api("api/citas/estado"), cargarEstadoIA()]);
  caja.innerHTML = `
    <div class="pagina">
      <div class="pagina-cabeza">
        <div>
          <h1>Líneas jurisprudenciales</h1>
          <p class="meta">Método de López Medina: problema jurídico con dos polos, punto arquimédico, ingeniería reversa,
            nicho citacional y ubicación de cada sentencia entre los polos.</p>
        </div>
      </div>
      ${red.disponible ? "" : `<div class="nota-ia" id="aviso-red">
        <b>Falta preparar la red de citas</b> (quién cita a quién en las ${num(69098)} sentencias). Se hace una sola vez y tarda unos 8 minutos.
        <button type="button" class="primario" id="preparar-red">Preparar red de citas</button>
        <span id="progreso-red" class="meta"></span></div>`}
      ${ia_.activa ? "" : `<div class="nota-ia">Sin IA la app arma la red de citas (nicho, prospectiva, contactos entre cortes), pero no ubica
        las sentencias entre los polos ni las clasifica. <a href="?vista=config" data-ir="config">Configurar DeepSeek</a></div>`}
      <form id="form-nueva-linea" class="tarjeta-config nueva-linea">
        <h2>Nueva línea</h2>
        <div class="modo-linea" role="radiogroup">
          <label class="opcion"><input type="radio" name="modo" value="tema" checked> Por problema jurídico</label>
          <label class="opcion"><input type="radio" name="modo" value="sentencia"> Desde una sentencia (punto arquimédico)</label>
        </div>
        <label id="campo-tema">Problema jurídico o tema
          <textarea id="entrada-tema" rows="3" placeholder="Ej.: ¿la terminación por fin de obra exime del permiso del inspector cuando el trabajador tiene fuero de salud?"></textarea></label>
        <label id="campo-sentencia" hidden>Radicado de la sentencia
          <input id="entrada-sentencia" placeholder="Ej.: T-076-24, SU-061 de 2023 o SL1152-2023"></label>
        <div class="fila">
          <label class="opcion"><input type="checkbox" name="corte-linea" value="csj" checked> Corte Suprema – Sala Laboral</label>
          <label class="opcion"><input type="checkbox" name="corte-linea" value="cc" checked> Corte Constitucional</label>
        </div>
        <p class="meta">La app propone el problema con sus dos polos y el punto arquimédico de cada corte; usted los ajusta antes de construir la línea.</p>
        <div class="fila"><button type="submit" class="primario">Proponer planteamiento</button></div>
      </form>
      <h2 class="titulo-seccion">Mis líneas</h2>
      <div class="lista-casos">
        ${lista.length ? lista.map(l => `
          <a class="tarjeta-caso" href="?vista=linea&linea=${l.id}" data-linea="${l.id}">
            <h3>${esc(l.titulo)}</h3>
            <p>${esc(l.planteamiento?.problema || l.entrada)}</p>
            <div class="meta">${{ planteando: "Proponiendo planteamiento…", planteada: "Lista para ajustar y construir", construyendo: "Construyendo…",
              lista: "Construida", error: "Con error" }[l.estado] || l.estado} · ${fechaCorta(l.actualizado)}</div>
          </a>`).join("") : `<div class="vacio">Todavía no hay líneas.</div>`}
      </div>
    </div>`;
  $$('[name="modo"]', caja).forEach(r => r.onchange = () => {
    const tema = $('[name="modo"]:checked', caja).value === "tema";
    $("#campo-tema").hidden = !tema;
    $("#campo-sentencia").hidden = tema;
  });
  $("#form-nueva-linea").onsubmit = async ev => {
    ev.preventDefault();
    const modo = $('[name="modo"]:checked', caja).value;
    const entrada = modo === "tema" ? $("#entrada-tema").value : $("#entrada-sentencia").value;
    const cortes = $$('[name="corte-linea"]:checked', caja).map(x => x.value);
    if (!cortes.length) { aviso("Marque al menos una corte."); return; }
    try {
      const l = await enviar("POST", "api/lineas", { usuario_id: u.id, modo, entrada, cortes });
      navegar({ vista: "linea", linea: l.id, ver: "" });
    } catch (err) { aviso(err.message); }
  };
  $$("[data-linea]", caja).forEach(a => a.onclick = ev => { ev.preventDefault(); navegar({ vista: "linea", linea: a.dataset.linea, ver: "" }); });
  $$("[data-ir]", caja).forEach(a => a.onclick = ev => { ev.preventDefault(); navegar({ vista: a.dataset.ir, ver: "" }); });
  const preparar = $("#preparar-red");
  if (preparar) preparar.onclick = async () => {
    preparar.disabled = true;
    await enviar("POST", "api/citas/construir");
    const t = setInterval(async () => {
      const e = await api("api/citas/estado").catch(() => null);
      if (!e) return;
      if (e.en_curso) { $("#progreso-red").textContent = `${num(e.hechas)} de ${num(e.total)} sentencias…`; return; }
      clearInterval(t);
      if (e.error) { $("#progreso-red").textContent = "No se pudo: " + e.error; preparar.disabled = false; }
      else { aviso("Red de citas lista"); pintarLineas(); }
    }, 2000);
  };
}

// ---------- Una línea ----------

async function pintarLinea(id) {
  const caja = $("#vista-linea");
  const u = await asegurarUsuario();
  if (!u || !id) return;
  if (!lineaActual || lineaActual.id !== id) { editandoPlanteamiento = false; filtroCorteLinea = ""; }
  caja.innerHTML = `<div class="pagina"><p class="meta">Cargando línea…</p></div>`;
  try { lineaActual = await api(`api/lineas/${id}`); } catch (err) { caja.innerHTML = `<div class="pagina"><p>${esc(err.message)}</p></div>`; return; }
  await cargarEstadoIA();
  const l = lineaActual;
  const cabeza = `
    <div class="pagina-cabeza">
      <div class="titulo-caso">
        <a href="?vista=lineas" class="enlace volver" data-ir="lineas">‹ Líneas</a>
        <input id="linea-titulo" class="titulo-editable" value="${esc(l.titulo)}" maxlength="200" aria-label="Título de la línea">
      </div>
      <div class="acciones">
        ${l.estado === "lista" ? `<a class="boton" href="api/lineas/${l.id}/word" download>Exportar Word</a>
          <a class="boton" href="api/lineas/${l.id}/excel" download>Exportar Excel</a>
          <button type="button" id="ajustar-linea">${editandoPlanteamiento ? "Ver la línea" : "Ajustar planteamiento"}</button>` : ""}
        <button type="button" id="eliminar-linea" class="peligro">Eliminar</button>
      </div>
    </div>`;
  let cuerpo;
  if (l.estado === "planteando" || l.estado === "construyendo") cuerpo = htmlProgresoLinea(l);
  else if (l.estado === "error") cuerpo = `<div class="error-analisis"><b>No se pudo completar.</b><br>${esc(l.error || "")}</div>` + htmlPlanteamiento(l);
  else if (l.estado === "planteada" || editandoPlanteamiento || !l.resultado) cuerpo = htmlPlanteamiento(l);
  else cuerpo = htmlResultadoLinea(l);
  caja.innerHTML = `<div class="pagina linea">${cabeza}${cuerpo}</div>`;
  conectarLinea(caja, u);
  if (l.estado === "planteando" || l.estado === "construyendo") seguirLinea(l.id);
}

function htmlProgresoLinea(l) {
  return `<div class="progreso">
    <p id="paso-linea">${esc(l.paso || "Iniciando")}</p>
    <div class="barra-progreso"><div id="progreso-linea" style="width:${l.progreso || 2}%"></div></div>
    <p class="meta">${l.estado === "planteando" ? "Proponiendo el problema, los polos y el punto arquimédico (menos de un minuto)."
      : "Siguiendo las citas y leyendo las sentencias. Con IA tarda de 2 a 6 minutos la primera vez; las sentencias ya leídas se reutilizan."}</p>
  </div>`;
}

function seguirLinea(id) {
  detenerSondeoLinea();
  sondeoLinea = setInterval(async () => {
    if (estado.vista !== "linea" || +estado.linea !== id) { detenerSondeoLinea(); return; }
    const l = await api(`api/lineas/${id}`).catch(() => null);
    if (!l) return;
    if (l.estado === "planteando" || l.estado === "construyendo") {
      const barra = $("#progreso-linea");
      if (barra) { barra.style.width = l.progreso + "%"; $("#paso-linea").textContent = l.paso || ""; }
      return;
    }
    detenerSondeoLinea();
    editandoPlanteamiento = false;
    pintarLinea(id);
    if (l.estado === "lista") aviso("Línea construida");
  }, 1800);
}

function htmlPlanteamiento(l) {
  const p = l.planteamiento || {};
  const cortes = p.cortes || ["csj", "cc"];
  const arq = corte => `
    <label>Punto arquimédico — ${NOMBRE_CORTE_LARGO[corte]}
      <input id="arq-${corte}" list="cand-${corte}" value="${esc((p.arquimedicas || {})[corte] || "")}" placeholder="Radicado de la sentencia más reciente con el mismo patrón fáctico">
      <datalist id="cand-${corte}">${((p.candidatas || {})[corte] || []).map(c => `<option value="${esc(c.radicado)}">${esc(c.radicado)} · ${c.ano} · ${esc(c.sala || "")}</option>`).join("")}</datalist>
    </label>
    ${(p.razon_arquimedica || {})[corte] ? `<p class="meta">Propuesta: ${esc(p.razon_arquimedica[corte])}</p>` : ""}
    ${((p.candidatas || {})[corte] || []).length ? `<p class="meta">Otras candidatas: ${p.candidatas[corte].slice(0, 6).map(c => `<a href="#" data-elegir-arq="${corte}" data-rad="${esc(c.radicado)}">${esc(c.radicado)}</a>`).join(" · ")}</p>` : ""}`;
  return `
    <form id="form-planteamiento" class="tarjeta-config planteamiento-linea">
      <h2>Planteamiento de la línea</h2>
      <p class="meta">${l.modo === "sentencia" ? `Punto de partida aportado: <b>${esc(l.entrada)}</b>. ` : ""}Revise y ajuste antes de construir.
        El problema debe estar en un nivel medio de abstracción y en términos fácticos.</p>
      <label>Problema jurídico (pregunta)
        <textarea id="pl-problema" rows="3">${esc(p.problema || "")}</textarea></label>
      <div class="polos-form">
        <label>Polo A (respuesta afirmativa extrema)
          <textarea id="pl-polo-a" rows="3">${esc(p.polo_a || "")}</textarea></label>
        <label>Polo B (respuesta negativa extrema)
          <textarea id="pl-polo-b" rows="3">${esc(p.polo_b || "")}</textarea></label>
      </div>
      <label>Patrón fáctico
        <textarea id="pl-patron" rows="2">${esc(p.patron_factico || "")}</textarea></label>
      <fieldset>
        <legend>Cortes</legend>
        <label class="opcion"><input type="checkbox" name="pl-corte" value="csj" ${cortes.includes("csj") ? "checked" : ""}> Corte Suprema – Sala Laboral</label>
        <label class="opcion"><input type="checkbox" name="pl-corte" value="cc" ${cortes.includes("cc") ? "checked" : ""}> Corte Constitucional</label>
      </fieldset>
      ${["csj", "cc"].map(c => `<div class="arq" data-corte-arq="${c}" ${cortes.includes(c) ? "" : "hidden"}>${arq(c)}</div>`).join("")}
      <div class="fila">
        <label class="compacto">Años <input id="pl-desde" type="number" min="1992" max="2100" placeholder="Desde" value="${p.desde || ""}">
          – <input id="pl-hasta" type="number" min="1992" max="2100" placeholder="Hasta" value="${p.hasta || ""}"></label>
        <label class="compacto">Niveles del nicho
          <select id="pl-profundidad">${[1, 2, 3].map(n => `<option value="${n}" ${(p.profundidad || 2) == n ? "selected" : ""}>${n}</option>`).join("")}</select></label>
        <label class="compacto">Tamaño
          <select id="pl-amplitud"><option value="normal">Hasta 30 sentencias</option><option value="amplia">Hasta 60 sentencias (más lento)</option></select></label>
      </div>
      <div class="fila">
        <button type="submit" class="primario grande">Construir línea</button>
        <button type="button" id="replantear">Volver a proponer</button>
      </div>
    </form>`;
}

// ---------- Resultado ----------

function htmlResultadoLinea(l) {
  const p = l.planteamiento, r = l.resultado;
  const sentencias = r.sentencias.filter(s => !filtroCorteLinea || s.corte_clave === filtroCorteLinea);
  const radicados = new Set(r.sentencias.map(s => s.radicado));
  const porRad = new Map(r.sentencias.map(s => [s.radicado, s]));
  const enlazar = texto => esc(texto || "")
    .replace(/\[([^\[\]]{3,40}?) — no está en la línea[^\]]*\]/g, (m, rad) => `<span class="cita-dudosa" title="No está entre las sentencias de la línea">[${rad} ⚠ no verificada]</span>`)
    .replace(/\[([^\[\]]{3,40})\]/g, (m, rad) => radicados.has(rad) ? `[<a href="#" data-ver="${porRad.get(rad).id}">${esc(rad)}</a>]` : m);

  const estados = Object.entries(r.por_corte).map(([corte, info]) => `
    <div class="estado-corte ${corte}">
      <h3>${NOMBRE_CORTE_LARGO[corte]}</h3>
      <p><span class="etiqueta ${ESTADOS_LINEA[info.estado?.estado] || ""}">${esc(info.estado?.estado || "—")}</span>
        <span class="meta">Última sentencia: ${esc(fechaLarga(info.ultima_sentencia, ""))} · ${info.n} sentencias · punto arquimédico ${esc(info.arquimedica || "—")}</span></p>
      <p class="meta">${esc(info.estado?.detalle || "")}</p>
      ${info.dominante ? `<p><b>Sentencia dominante:</b> <a href="#" data-ver="${porRad.get(info.dominante)?.id}">${esc(info.dominante)}</a></p>` : ""}
      ${(info.advertencias || []).map(a => `<p class="revision">${esc(a)}</p>`).join("")}
      ${(info.disidencias_recurrentes || []).length ? `<p class="meta"><b>Disidencias recurrentes:</b> ${info.disidencias_recurrentes.map(d => `${esc(d.magistrado)} (${d.salvamentos} salvamentos)`).join("; ")}</p>` : ""}
    </div>`).join("");

  const balance = Object.entries(r.por_corte).filter(([, i]) => i.doctrina_vigente).map(([corte, info]) => `
    <div class="balance-corte">
      <h4>${NOMBRE_CORTE_LARGO[corte]}</h4>
      <p><b>Doctrina vigente:</b> ${enlazar(info.doctrina_vigente)}</p>
      ${info.evolucion ? `<p><b>Evolución de las subreglas:</b> ${enlazar(info.evolucion)}</p>` : ""}
      ${info.vacios ? `<p class="vacios"><b>Vacíos:</b> ${esc(info.vacios)}</p>` : ""}
    </div>`).join("");

  const filtros = `<div class="filtro-cuestiones">
    <button type="button" data-filtro-corte="" ${!filtroCorteLinea ? 'aria-pressed="true"' : ""}>Ambas cortes</button>
    ${Object.keys(r.por_corte).map(c => `<button type="button" data-filtro-corte="${c}" ${filtroCorteLinea === c ? 'aria-pressed="true"' : ""}>${NOMBRE_CORTE_LARGO[c]}</button>`).join("")}
  </div>`;

  return `
    <div class="planteamiento problema-linea">
      <h3>Problema jurídico</h3>
      <p class="pregunta">${esc(p.problema || "—")}</p>
      <div class="polos"><div class="polo polo-a"><b>Polo A (1)</b> ${esc(p.polo_a || "—")}</div><div class="polo polo-b"><b>Polo B (5)</b> ${esc(p.polo_b || "—")}</div></div>
      ${p.patron_factico ? `<p class="meta"><b>Patrón fáctico:</b> ${esc(p.patron_factico)}</p>` : ""}
    </div>
    <div class="estados-linea">${estados}</div>
    ${r.con_ia ? `<h3 class="titulo-seccion">Gráfico de la línea</h3>${filtros}<div id="grafico-linea" class="grafico-linea" data-sin-tabla></div>
      <details class="tabla-lopez-detalle"><summary>Ver como tabla (formato López Medina)</summary>${htmlTablasLopez(l)}</details>` : filtros}
    ${balance || r.relacion?.relacion ? `<h3 class="titulo-seccion">Balance</h3><div class="sintesis">${balance}
      ${r.relacion?.relacion ? `<div class="balance-corte"><h4>Relación entre las cortes</h4><p>${enlazar(r.relacion.relacion)}</p></div>` : ""}
      ${r.relacion?.subregla_de_derecho ? `<p class="subregla-final"><b>Subregla de derecho:</b> ${esc(r.relacion.subregla_de_derecho)}</p>` : ""}
      <p class="meta">Generado con IA a partir de las ubicaciones verificadas: revise las sentencias antes de citar.</p></div>` : ""}
    <h3 class="titulo-seccion">Nicho citacional</h3>
    ${htmlNicho(r)}
    ${r.contactos.length ? `<h3 class="titulo-seccion">Puntos de contacto entre las cortes</h3>
      <ul class="contactos">${r.contactos.map(x => `<li><b>${esc(x.origen)}</b> cita <b>${esc(x.destino)}</b>${x.en_nota ? " (nota al pie)" : ""}${x.fuera_de_linea ? ' <span class="meta">(fuera de la línea)</span>' : ""}
        <blockquote class="cita-textual verificada">«${esc(x.contexto)}» <span class="sello">✓ texto literal</span>
        ${porRad.get(x.origen) ? `<a href="#" data-cita-id="${porRad.get(x.origen).id}" data-cita="${esc(x.contexto)}">ver en el texto</a>` : ""}</blockquote></li>`).join("")}</ul>` : ""}
    <h3 class="titulo-seccion">Sentencias de la línea</h3>
    ${filtros}
    <ol class="lista-precedentes">${sentencias.map(s => htmlSentenciaLinea(s)).join("")}</ol>`;
}

function htmlTablasLopez(l) {
  const p = l.planteamiento, r = l.resultado;
  return Object.keys(r.por_corte).map(corte => {
    const ubicadas = r.sentencias.filter(s => s.corte_clave === corte && s.posicion);
    if (!ubicadas.length) return "";
    return `<table class="tabla-lopez"><caption>${NOMBRE_CORTE_LARGO[corte]}</caption>
      <thead><tr><th>Polo A</th><th>1</th><th>2</th><th>3</th><th>4</th><th>5</th><th>Polo B</th></tr>
      <tr><td class="polo-celda">${esc(p.polo_a || "")}</td><td></td><td></td><td></td><td></td><td></td><td class="polo-celda">${esc(p.polo_b || "")}</td></tr></thead>
      <tbody>${ubicadas.map(s => `<tr><td></td>${[1, 2, 3, 4, 5].map(n => `<td>${n === s.posicion ? `<a href="#" data-ver="${s.id}" class="${(s.clase || "").startsWith("hito") || s.clase === "fundadora" ? "hito" : ""}">${esc(s.radicado)}</a>${s.clase === "no_fija_linea" ? " *" : ""}` : ""}</td>`).join("")}<td></td></tr>`).join("")}</tbody>
    </table>`;
  }).join("") + `<p class="meta">En negrilla, fundadoras e hito; con *, las que no fijan línea.</p>`;
}

function htmlNicho(r) {
  const niveles = {};
  r.sentencias.forEach(s => { if (s.nivel != null) (niveles[s.nivel] = niveles[s.nivel] || []).push(s); });
  const chip = s => `<a href="#" class="chip-sentencia ${s.corte_clave}" data-ver="${s.id}" title="${esc(s.peso.etiqueta)}${s.citada_en_linea ? ` · citada ${s.citada_en_linea} veces en la línea` : ""}">${esc(s.radicado)}${s.citada_en_linea >= 3 ? ` <b>${s.citada_en_linea}</b>` : ""}</a>`;
  const nodales = [...r.sentencias].filter(s => s.citada_en_linea).sort((a, b) => b.citada_en_linea - a.citada_en_linea).slice(0, 8);
  const prosp = r.sentencias.filter(s => s.origen.includes("prospectiva"));
  return `<div class="nicho">
    ${Object.keys(niveles).sort().map(n => `<div class="nivel-nicho"><span class="etiqueta-nivel">${n == 0 ? "Punto arquimédico" : `Nivel ${n}`}</span>
      <div class="chips">${niveles[n].map(chip).join(" ")}</div></div>`).join("")}
    ${nodales.length ? `<div class="nivel-nicho"><span class="etiqueta-nivel">Puntos nodales</span><div class="chips">${nodales.map(chip).join(" ")}</div>
      <span class="meta">El número es cuántas sentencias de la línea la citan.</span></div>` : ""}
    ${prosp.length ? `<div class="nivel-nicho"><span class="etiqueta-nivel">Posteriores que la citan</span><div class="chips">${prosp.map(chip).join(" ")}</div></div>` : ""}
    ${r.no_en_base.length ? `<div class="nivel-nicho"><span class="etiqueta-nivel">Citadas, no están en la base</span>
      <div class="chips">${r.no_en_base.slice(0, 15).map(x => `<span class="chip-sentencia">${esc(x.radicado.replace("rad:", "rad. "))} (${x.veces})</span>`).join(" ")}</div></div>` : ""}
  </div>`;
}

function htmlSentenciaLinea(s) {
  const fi = s.ficha;
  const posicion = s.posicion ? `<div class="puntaje posicion" title="Posición entre el polo A (1) y el polo B (5)">${s.posicion}</div>` : `<div class="puntaje sin" title="No aborda el problema o no se ubicó">—</div>`;
  return `<li class="precedente ${s.corte_clave}" id="lin-${esc(s.radicado).replace(/[^\w-]/g, "_")}">
    ${posicion}
    <div class="precedente-cuerpo">
      <h4><a href="#" data-ver="${s.id}">${esc(s.tipo || "")} ${esc(s.radicado)}</a>
        ${s.clase ? `<span class="etiqueta clase-${s.clase}">${CLASES_LINEA[s.clase]}</span>` : ""}
        <span class="etiqueta peso-${s.peso.nivel}" title="${esc(s.peso.nota)}">${esc(s.peso.etiqueta)}</span>
        ${s.origen.map(o => `<span class="etiqueta">${esc(o)}</span>`).join("")}</h4>
      <div class="meta">${esc(NOMBRE_CORTE_LARGO[s.corte_clave])} · ${esc(fechaLarga(s.fecha, s.ano))}${s.ponente ? " · M.P. " + esc(s.ponente) : ""}
        ${s.citada_en_linea ? ` · citada ${s.citada_en_linea} ${s.citada_en_linea === 1 ? "vez" : "veces"} en la línea` : ""}</div>
      ${s.aborda_problema === false ? `<p class="meta">No aborda este problema jurídico.</p>` : ""}
      ${s.clase === "no_fija_linea" && s.motivo_no_fija ? `<p class="revision"><b>No fija línea:</b> ${esc(s.motivo_no_fija)}</p>` : ""}
      ${s.justificacion ? `<p><b>Ubicación:</b> ${esc(s.justificacion)}${s.fundamento ? ` <span class="meta">(${esc(s.fundamento)})</span>` : ""}</p>` : ""}
      ${s.cita ? citaHtml(s.cita, s.cita_verificada, s.id) : ""}
      ${s.razon_clase ? `<p class="meta"><b>Clasificación:</b> ${esc(s.razon_clase)}</p>` : ""}
      ${s.subregla ? `<p><b>Subregla:</b> ${esc(s.subregla)}</p>` : ""}
      ${s.cita_a.length ? `<p class="meta"><b>Cita en la línea:</b> ${s.cita_a.map(c => {
        const uso = (s.usos || []).find(u => u.rad === c.radicado);
        return `${esc(c.radicado)} (${c.veces}×${c.en_nota ? ", en nota" : ""}${c.en_antecedentes && !c.en_consideraciones ? ", solo en antecedentes" : ""}${c.en_salvamento ? ", en voto particular" : ""}${uso ? ": " + USO_CITA[uso.uso] : ""})`;
      }).join("; ")}</p>` : ""}
      ${(s.votos || []).length ? `<p class="meta"><b>Votos particulares:</b> ${s.votos.map(v => `${v.tipo === "salvamento" ? "salvamento" : "aclaración"}${v.parcial ? " parcial" : ""} de ${esc(v.magistrado)}`).join("; ")}</p>` : ""}
      ${fi ? `<details><summary>Ficha neutra</summary>
        <p><b>Resultado:</b> ${esc(fi.resultado.efecto)}</p>
        ${fi.problema_juridico ? `<p><b>Problema que resolvió:</b> ${esc(fi.problema_juridico)}</p>` : ""}
        <ul>${fi.hechos.map(h => `<li>${esc(h)}</li>`).join("")}</ul></details>` : ""}
    </div>
  </li>`;
}

// ---------- Gráfico tiempo contra posición (SVG) ----------

function anoDecimal(s) {
  if (s.fecha) { const [a, m, d] = s.fecha.split("-").map(Number); return a + (m - 1) / 12 + (d - 1) / 365; }
  return (s.ano || 2000) + 0.5;
}

function marcador(s, x, y, color) {
  const lleno = s.peso.nivel >= 3;
  const relleno = lleno ? color : "var(--panel)";
  const comun = `fill="${relleno}" stroke="${color}" stroke-width="2"`;
  const anillo = `<circle cx="${x}" cy="${y}" r="9" fill="var(--panel)" opacity=".9"/>`;
  switch (s.clase) {
    case "fundadora": return anillo + `<path d="M${x} ${y - 8} L${x + 8} ${y} L${x} ${y + 8} L${x - 8} ${y} Z" ${comun}/>`;
    case "hito_consolidadora": case "hito_modificadora": case "hito_reconceptualizadora":
      return anillo + `<rect x="${x - 6.5}" y="${y - 6.5}" width="13" height="13" rx="2" ${comun}/>`;
    case "no_fija_linea": return `<path d="M${x - 5} ${y - 5} L${x + 5} ${y + 5} M${x + 5} ${y - 5} L${x - 5} ${y + 5}" stroke="${color}" stroke-width="2.5" stroke-linecap="round"/>`;
    default: return anillo + `<circle cx="${x}" cy="${y}" r="6" ${comun}/>`;
  }
}

function dibujarGraficoLinea() {
  const caja = $("#grafico-linea");
  if (!caja || !lineaActual?.resultado) return;
  const p = lineaActual.planteamiento;
  const puntos = lineaActual.resultado.sentencias.filter(s => s.posicion && (!filtroCorteLinea || s.corte_clave === filtroCorteLinea));
  if (!puntos.length) { caja.innerHTML = `<p class="meta">No hay sentencias ubicadas entre los polos.</p>`; return; }
  const ancho = Math.max(320, caja.clientWidth);
  const angosto = ancho < 600;
  const m = { izq: angosto ? 34 : 46, der: 16, arr: 16, aba: 34 };
  const alto = 300;
  const anos = puntos.map(anoDecimal);
  let x0 = Math.floor(Math.min(...anos)) - 1, x1 = Math.ceil(Math.max(...anos)) + 1;
  const X = a => m.izq + (a - x0) / (x1 - x0) * (ancho - m.izq - m.der);
  const Y = pos => m.arr + (pos - 1) / 4 * (alto - m.arr - m.aba);
  const paso = Math.max(1, Math.ceil((x1 - x0) / (angosto ? 5 : 10)));
  const colores = { cc: "var(--serie-cc)", csj: "var(--serie-csj)" };
  // Separación leve de puntos que caen casi en el mismo lugar.
  const ocupados = {};
  const pos = puntos.map(s => {
    let x = X(anoDecimal(s)), y = Y(s.posicion);
    const k = `${Math.round(x / 10)}|${s.posicion}`;
    const n = ocupados[k] = (ocupados[k] || 0) + 1;
    if (n > 1) y += (n % 2 ? 1 : -1) * Math.ceil((n - 1) / 2) * 9;
    return { s, x, y };
  });
  let svg = `<svg viewBox="0 0 ${ancho} ${alto}" width="100%" height="${alto}" role="img" aria-label="Gráfico de la línea: año contra posición entre polos">`;
  for (let n = 1; n <= 5; n++) {
    svg += `<line x1="${m.izq}" x2="${ancho - m.der}" y1="${Y(n)}" y2="${Y(n)}" stroke="var(--borde)" stroke-width="1" ${n === 3 ? 'stroke-dasharray="4 4"' : ""}/>`;
    svg += `<text x="${m.izq - 8}" y="${Y(n) + 4}" text-anchor="end" class="eje">${n === 1 ? "A·1" : n === 5 ? "B·5" : n}</text>`;
  }
  for (let a = Math.ceil(x0 / paso) * paso; a <= x1; a += paso) {
    svg += `<text x="${X(a)}" y="${alto - 10}" text-anchor="middle" class="eje">${a}</text>`;
  }
  pos.forEach(({ s, x, y }, i) => {
    svg += `<g class="punto" data-i="${i}" tabindex="0">${marcador(s, x, y, colores[s.corte_clave])}<circle cx="${x}" cy="${y}" r="14" fill="transparent"/></g>`;
  });
  svg += `</svg>`;
  const cortes = [...new Set(puntos.map(s => s.corte_clave))];
  caja.innerHTML = `
    <div class="leyenda-linea">
      ${cortes.map(c => `<span><svg width="14" height="14"><circle cx="7" cy="7" r="6" fill="${colores[c]}"/></svg> ${NOMBRE_CORTE_LARGO[c]}</span>`).join("")}
      <span><svg width="16" height="16"><path d="M8 1 L15 8 L8 15 L1 8 Z" fill="none" stroke="currentColor" stroke-width="1.6"/></svg> Fundadora</span>
      <span><svg width="14" height="14"><rect x="1.5" y="1.5" width="11" height="11" rx="2" fill="none" stroke="currentColor" stroke-width="1.6"/></svg> Hito</span>
      <span><svg width="14" height="14"><circle cx="7" cy="7" r="5.5" fill="none" stroke="currentColor" stroke-width="1.6"/></svg> Confirmadora</span>
      <span><svg width="14" height="14"><path d="M3 3 L11 11 M11 3 L3 11" stroke="currentColor" stroke-width="2"/></svg> No fija línea</span>
      <span class="meta">Relleno: Sala Plena o Sala permanente · Hueco: Sala de Revisión o de Descongestión</span>
    </div>
    <div class="polos-grafico"><span>Polo A: ${esc(p.polo_a || "")}</span><span>Polo B: ${esc(p.polo_b || "")}</span></div>
    <div class="lienzo-grafico">${svg}<div class="tooltip-linea" hidden></div></div>`;
  const tip = $(".tooltip-linea", caja);
  $$(".punto", caja).forEach(g => {
    const { s, x, y } = pos[+g.dataset.i];
    const mostrar = () => {
      tip.innerHTML = `<b>${esc(s.radicado)}</b> · ${esc(fechaLarga(s.fecha, s.ano))}<br>${esc(s.peso.etiqueta)}<br>
        Posición ${s.posicion}${s.clase ? " · " + CLASES_LINEA[s.clase] : ""}${s.justificacion ? `<br><span class="meta">${esc(s.justificacion.slice(0, 160))}</span>` : ""}`;
      tip.hidden = false;
      const izquierda = Math.min(Math.max(0, x - 120), ancho - 250);
      tip.style.left = izquierda + "px";
      tip.style.top = (y > alto / 2 ? y - tip.offsetHeight - 14 : y + 16) + "px";
    };
    g.addEventListener("mouseenter", mostrar);
    g.addEventListener("focus", mostrar);
    g.addEventListener("mouseleave", () => (tip.hidden = true));
    g.addEventListener("blur", () => (tip.hidden = true));
    g.addEventListener("click", () => navegar({ ver: s.id }));
  });
}

// ---------- Acciones ----------

function conectarLinea(caja, u) {
  const l = lineaActual;
  $$("[data-ir]", caja).forEach(a => a.onclick = ev => { ev.preventDefault(); navegar({ vista: a.dataset.ir, linea: "", ver: "" }); });
  $("#linea-titulo").onchange = async () => {
    await enviar("PUT", `api/lineas/${l.id}`, { titulo: $("#linea-titulo").value.trim() || "Línea sin título" }).catch(err => aviso(err.message));
  };
  $("#eliminar-linea").onclick = async () => {
    if (!confirm(`¿Eliminar la línea "${l.titulo}"? No se puede deshacer.`)) return;
    await enviar("DELETE", `api/lineas/${l.id}`);
    lineaActual = null;
    navegar({ vista: "lineas", linea: "" });
  };
  const ajustar = $("#ajustar-linea");
  if (ajustar) ajustar.onclick = () => { editandoPlanteamiento = !editandoPlanteamiento; pintarLinea(l.id); };
  $$("[data-ver]", caja).forEach(a => a.onclick = ev => { ev.preventDefault(); if (a.dataset.ver && a.dataset.ver !== "undefined") navegar({ ver: a.dataset.ver }); });
  $$("[data-cita-id]", caja).forEach(a => a.onclick = ev => {
    ev.preventDefault();
    window.citaLector = a.dataset.cita;
    if (String(estado.ver) === a.dataset.citaId) irACita(); else navegar({ ver: a.dataset.citaId });
  });
  $$("[data-filtro-corte]", caja).forEach(b => b.onclick = () => { filtroCorteLinea = b.dataset.filtroCorte; pintarLinea(l.id); });
  const form = $("#form-planteamiento");
  if (form) {
    $$('[name="pl-corte"]', form).forEach(x => x.onchange = () => {
      $$("[data-corte-arq]", form).forEach(d => (d.hidden = !$(`[name="pl-corte"][value="${d.dataset.corteArq}"]`, form).checked));
    });
    $$("[data-elegir-arq]", form).forEach(a => a.onclick = ev => { ev.preventDefault(); $(`#arq-${a.dataset.elegirArq}`).value = a.dataset.rad; });
    const datos = () => {
      const cortes = $$('[name="pl-corte"]:checked', form).map(x => x.value);
      const arquimedicas = {};
      cortes.forEach(c => { const v = $(`#arq-${c}`).value.trim(); if (v) arquimedicas[c] = v; });
      return {
        problema: $("#pl-problema").value.trim(), polo_a: $("#pl-polo-a").value.trim(), polo_b: $("#pl-polo-b").value.trim(),
        patron_factico: $("#pl-patron").value.trim(), cortes, arquimedicas,
        desde: +$("#pl-desde").value || null, hasta: +$("#pl-hasta").value || null, profundidad: +$("#pl-profundidad").value,
      };
    };
    form.onsubmit = async ev => {
      ev.preventDefault();
      const d = datos();
      if (!d.cortes.length) { aviso("Marque al menos una corte."); return; }
      if (!Object.keys(d.arquimedicas).length) { aviso("Indique al menos un punto arquimédico."); return; }
      try {
        await enviar("PUT", `api/lineas/${l.id}`, d);
        await enviar("POST", `api/lineas/${l.id}/construir`, { amplitud: $("#pl-amplitud").value });
        editandoPlanteamiento = false;
        pintarLinea(l.id);
      } catch (err) { aviso(err.message); }
    };
    $("#replantear").onclick = async () => {
      if (!confirm("La app volverá a proponer el problema, los polos y los puntos arquimédicos a partir de la entrada original. Los campos que usted ya llenó se conservan.")) return;
      try {
        await enviar("PUT", `api/lineas/${l.id}`, datos());
        await enviar("POST", `api/lineas/${l.id}/construir`, { replantear: true });
        pintarLinea(l.id);
      } catch (err) { aviso(err.message); }
    };
  }
  if ($("#grafico-linea")) requestAnimationFrame(dibujarGraficoLinea);
}

window.addEventListener("resize", () => { if (estado.vista === "linea") dibujarGraficoLinea(); });
