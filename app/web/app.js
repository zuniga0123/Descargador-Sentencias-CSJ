"use strict";
// Interfaz del buscador. Todo el estado vive en la URL (?q=...&tema=...&ver=id)
// para que funcione el botón Atrás y se puedan compartir enlaces dentro de la red.

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const FACETAS = ["corte", "sala", "tipo", "tema", "ponente"];
const NOMBRES_CORTE = { csj: "Corte Suprema – Sala Laboral", cc: "Corte Constitucional" };
let estado = leerURL();
let ultimo = null;
let datosEstado = null;

function leerURL() {
  const p = new URLSearchParams(location.search);
  const e = { q: p.get("q") || "", orden: p.get("orden") || "relevancia", pagina: +p.get("pagina") || 1,
              desde: p.get("desde") || "", hasta: p.get("hasta") || "", ver: p.get("ver") || "",
              vista: p.get("vista") || "", caso: p.get("caso") || "" };
  FACETAS.forEach(f => (e[f] = p.getAll(f)));
  return e;
}

function aParams(e, conVer = true) {
  const p = new URLSearchParams();
  if (e.vista) p.set("vista", e.vista);
  if (e.vista === "caso" && e.caso) p.set("caso", e.caso);
  if (e.q) p.set("q", e.q);
  FACETAS.forEach(f => e[f].forEach(v => p.append(f, v)));
  ["desde", "hasta"].forEach(k => e[k] && p.set(k, e[k]));
  if (e.orden !== "relevancia") p.set("orden", e.orden);
  if (e.pagina > 1) p.set("pagina", e.pagina);
  if (conVer && e.ver) p.set("ver", e.ver);
  return p;
}

function navegar(cambios, { reemplazar = false } = {}) {
  estado = { ...estado, ...cambios };
  const url = "?" + aParams(estado).toString();
  reemplazar ? history.replaceState(null, "", url) : history.pushState(null, "", url);
  render();
}

window.addEventListener("popstate", () => { estado = leerURL(); render(); });

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = n => Number(n).toLocaleString("es-CO");
const sinTildes = s => s.normalize("NFD").replace(/[̀-ͯ]/g, "");

function aviso(texto) {
  const a = $("#aviso");
  a.textContent = texto; a.hidden = false;
  clearTimeout(aviso.t); aviso.t = setTimeout(() => (a.hidden = true), 2200);
}

async function api(ruta) {
  const r = await fetch(ruta);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

// ---------- Vistas ----------

function mostrarVista(vista) {
  $("main.contenedor").hidden = !!vista;
  $$(".vista").forEach(v => (v.hidden = v.id !== "vista-" + vista));
  $$(".menu [data-vista]").forEach(a => a.classList.toggle("activo", a.dataset.vista === (vista === "caso" ? "casos" : vista)));
}

// ---------- Búsqueda ----------

const hayBusqueda = () => estado.q || estado.desde || estado.hasta || FACETAS.some(f => estado[f].length);

let pendiente = 0;
async function render() {
  $("#q").value = estado.q;
  $("#orden").value = estado.orden;
  $("#desde").value = estado.desde;
  $("#hasta").value = estado.hasta;
  document.title = estado.q ? `${estado.q} · Buscador de Jurisprudencia` : "Buscador de Jurisprudencia";
  mostrarVista(estado.vista);
  const clave = aParams(estado, false).toString();
  if (estado.vista) {
    renderVista(estado.vista);  // casos.js
  } else if (!hayBusqueda()) {
    mostrarBienvenida();
  } else if (clave !== ultimo?.clave) {
    const turno = ++pendiente;
    $(".resultados").classList.add("cargando");
    try {
      const datos = await api("api/buscar?" + clave);
      if (turno !== pendiente) return;
      ultimo = { clave, datos };
      pintarResultados(datos);
    } catch (err) {
      if (turno !== pendiente) return;
      $("#lista").innerHTML = `<li class="exacta">${esc(err.message)}</li>`;
    } finally {
      if (turno === pendiente) $(".resultados").classList.remove("cargando");
    }
  }
  if (estado.ver) abrirLector(estado.ver); else cerrarLector(false);
}

async function mostrarBienvenida() {
  ultimo = null;
  ["#lista", "#paginacion", "#exactas", "#conteo"].forEach(s => ($(s).innerHTML = ""));
  FACETAS.forEach(f => ($(`[data-faceta="${f}"] .opciones`).innerHTML = ""));
  $("#histograma").innerHTML = "";
  const b = $("#bienvenida");
  b.hidden = false;
  if (!datosEstado) datosEstado = await api("api/estado").catch(() => ({ lista: false, mensaje: "No se pudo conectar con el servidor." }));
  if (!datosEstado.lista) { b.innerHTML = `<h2>Falta preparar la base</h2><p>${esc(datosEstado.mensaje)}</p>`; return; }
  // Filtros con los conteos de toda la colección, para empezar filtrando.
  api("api/buscar?por_pagina=1").then(d => { if (!hayBusqueda()) pintarFacetas(d.facetas); }).catch(() => {});
  const cortes = datosEstado.cortes.map(c => `<div><b>${num(c.n)}</b>${esc(NOMBRES_CORTE[c.corte_clave] || c.corte)} · ${c.desde}–${c.hasta}</div>`).join("");
  const ejemplos = ['"estabilidad laboral reforzada"', '"contrato realidad" prestación de servicios', '"pensión de sobrevivientes" compañera permanente',
                    '"indemnización moratoria" buena fe', '"mínimo vital" tutela', 'T-760/08'];
  b.innerHTML = `
    <h2>Busca en ${num(datosEstado.total)} sentencias</h2>
    <div class="cifras">${cortes}</div>
    <p>Escribe palabras, una "frase exacta" o un radicado. Después afina con los filtros de la izquierda.</p>
    <div class="sugerencias">${ejemplos.map(e => `<button type="button" data-q="${esc(e)}">${esc(e)}</button>`).join("")}</div>
    <p class="meta">Base actualizada: ${esc(datosEstado.construida || "—")}. Para traer sentencias nuevas ejecuta <code>actualizar.bat</code>.</p>`;
  $$("[data-q]", b).forEach(x => x.onclick = () => navegar({ q: x.dataset.q, pagina: 1 }));
}

function pintarResultados(d) {
  $("#bienvenida").hidden = true;
  $("#conteo").textContent = d.total === 1 ? "1 sentencia" : `${num(d.total)} sentencias`;
  $("#exactas").innerHTML = d.exactas.length
    ? `<div class="exacta">Coincidencia exacta de radicado: ${d.exactas.map(x =>
        `<a href="?${aParams({ ...estado, ver: x.id })}" data-ver="${x.id}"><b>${esc(x.radicado)}</b></a> (${esc(x.corte)}, ${x.ano})`).join(" · ")}</div>`
    : "";
  $("#lista").innerHTML = d.resultados.map(tarjeta).join("") ||
    `<li class="exacta">No se encontraron sentencias. Prueba con menos palabras, quita filtros o usa O entre alternativas.</li>`;
  $$("[data-ver]").forEach(el => el.addEventListener("click", ev => {
    if (ev.target.closest("a") && (ev.ctrlKey || ev.metaKey)) return;
    ev.preventDefault();
    navegar({ ver: el.dataset.ver });
  }));
  pintarFacetas(d.facetas);
  pintarPaginacion(d);
}

function tarjeta(r) {
  const terminos = (ultimo && estado.q) ? terminosDe(estado.q) : [];
  const fecha = r.fecha ? new Date(r.fecha + "T12:00").toLocaleDateString("es-CO", { day: "numeric", month: "long", year: "numeric" }) : r.ano;
  const temas = [r.tema, r.subtema].filter(t => t && !/^Otros|^Sin subtema/.test(t)).join(" › ");
  return `<li class="tarjeta ${r.corte_clave}" data-ver="${r.id}">
    <h3><a href="?${aParams({ ...estado, ver: r.id })}">${esc(r.radicado)}</a>
      <span class="etiqueta">${esc(r.tipo)}</span>
      ${r.radicacion ? `<span class="etiqueta">Rad. ${esc(r.radicacion)}</span>` : ""}</h3>
    <div class="meta">${esc(NOMBRES_CORTE[r.corte_clave] || r.corte)} · ${esc(r.sala || "")} · ${esc(fecha)}${r.ponente ? " · M.P. " + esc(r.ponente) : ""}</div>
    <p class="fragmento">${resaltar(esc(r.fragmento), terminos)}</p>
    ${temas ? `<div class="temas">${esc(temas)}</div>` : ""}
  </li>`;
}

function pintarFacetas(f) {
  for (const nombre of FACETAS) {
    const caja = $(`[data-faceta="${nombre}"] .opciones`);
    const marcados = new Set(estado[nombre]);
    const valores = [...(f[nombre] || [])];
    // Mantener visibles los marcados aunque ya no tengan resultados.
    marcados.forEach(v => valores.some(x => String(x.valor) === v) || valores.unshift({ valor: v, n: 0 }));
    caja.innerHTML = valores.map(({ valor, n }) => {
      const etiqueta = nombre === "corte" ? (NOMBRES_CORTE[valor] || valor) : valor;
      return `<label class="opcion"><input type="checkbox" value="${esc(valor)}" ${marcados.has(String(valor)) ? "checked" : ""}>
        <span>${esc(etiqueta)}</span><span class="n">${num(n)}</span></label>`;
    }).join("") || `<span class="meta">—</span>`;
    $$("input", caja).forEach(inp => inp.onchange = () => {
      const set = new Set(estado[nombre]);
      inp.checked ? set.add(inp.value) : set.delete(inp.value);
      navegar({ [nombre]: [...set], pagina: 1 });
    });
    const filtro = $(`[data-faceta="${nombre}"] .filtrar`);
    if (filtro) { filtro.oninput = () => filtrarOpciones(caja, filtro.value); filtrarOpciones(caja, filtro.value); }
  }
  const anos = f.ano || [];
  const max = Math.max(1, ...anos.map(a => a.n));
  $("#histograma").innerHTML = anos.map(a => `<div style="height:${Math.max(4, (a.n / max) * 100)}%" title="${a.valor}: ${num(a.n)}" data-ano="${a.valor}"></div>`).join("");
  $$("#histograma [data-ano]").forEach(x => x.onclick = () => navegar({ desde: x.dataset.ano, hasta: x.dataset.ano, pagina: 1 }));
}

function filtrarOpciones(caja, texto) {
  const t = sinTildes(texto.toLowerCase());
  $$(".opcion", caja).forEach(o => (o.hidden = t && !sinTildes(o.textContent.toLowerCase()).includes(t)));
}

function pintarPaginacion(d) {
  const paginas = Math.min(500, Math.ceil(d.total / d.por_pagina));
  if (paginas <= 1) { $("#paginacion").innerHTML = ""; return; }
  const actual = d.pagina, nums = new Set([1, paginas, actual - 2, actual - 1, actual, actual + 1, actual + 2]);
  let html = actual > 1 ? `<button data-p="${actual - 1}">‹ Anterior</button>` : "";
  let previo = 0;
  [...nums].filter(n => n >= 1 && n <= paginas).sort((a, b) => a - b).forEach(n => {
    if (n - previo > 1) html += `<span>…</span>`;
    html += `<button data-p="${n}" ${n === actual ? 'aria-current="page"' : ""}>${n}</button>`;
    previo = n;
  });
  if (actual < paginas) html += `<button data-p="${actual + 1}">Siguiente ›</button>`;
  $("#paginacion").innerHTML = html;
  $$("#paginacion [data-p]").forEach(b => b.onclick = () => { navegar({ pagina: +b.dataset.p }); scrollTo(0, 0); });
}

// ---------- Resaltado ----------

function terminosDe(q) {
  const t = [];
  for (const m of q.matchAll(/(-?)"([^"]+)"|(\S+)/g)) {
    if (m[1] === "-" || (m[3] || "").startsWith("-")) continue;
    const v = (m[2] || m[3]).replace(/\*$/, "");
    if (!/^(O|OR)$/i.test(v) && v.length >= 2) t.push(v);
  }
  return t;
}

function patron(terminos) {
  const piezas = terminos.map(t => (sinTildes(t.toLowerCase()).match(/[\p{L}\p{N}]+/gu) || [])
    .map(p => p.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("[^\\p{L}\\p{N}]+")).filter(Boolean);
  return piezas.length ? new RegExp(`(?<![\\p{L}\\p{N}])(${piezas.join("|")})`, "giu") : null;
}

// Resalta sobre texto ya escapado (para tarjetas).
function resaltar(html, terminos) {
  const re = patron(terminos);
  if (!re) return html;
  const base = sinTildes(html);
  let salida = "", i = 0;
  for (const m of base.matchAll(re)) {
    salida += html.slice(i, m.index) + "<mark>" + html.slice(m.index, m.index + m[0].length) + "</mark>";
    i = m.index + m[0].length;
  }
  return salida + html.slice(i);
}

// Resalta dentro de un elemento del DOM; devuelve las marcas creadas.
function resaltarDOM(raiz, terminos, clase = "") {
  const re = patron(terminos);
  if (!re) return [];
  const nodos = [], marcas = [];
  const w = document.createTreeWalker(raiz, NodeFilter.SHOW_TEXT);
  while (w.nextNode()) nodos.push(w.currentNode);
  for (const nodo of nodos) {
    const texto = nodo.nodeValue, base = sinTildes(texto);
    if (base.length !== texto.length) continue;
    const coincidencias = [...base.matchAll(re)];
    if (!coincidencias.length) continue;
    const frag = document.createDocumentFragment();
    let i = 0;
    for (const m of coincidencias) {
      frag.append(texto.slice(i, m.index));
      const mk = document.createElement("mark");
      if (clase) mk.className = clase;
      mk.textContent = texto.slice(m.index, m.index + m[0].length);
      frag.append(mk); marcas.push(mk);
      i = m.index + m[0].length;
    }
    frag.append(texto.slice(i));
    nodo.replaceWith(frag);
  }
  return marcas;
}

function quitarMarcas(raiz, clase) {
  $$(`mark.${clase}`, raiz).forEach(m => m.replaceWith(m.textContent));
  raiz.normalize();
}

// ---------- Lector ----------

let abierta = null;
async function abrirLector(id) {
  const lector = $("#lector");
  if (abierta?.id == id) { lector.hidden = false; return; }
  lector.hidden = false;
  document.body.style.overflow = "hidden";
  $("#lector-titulo").textContent = "Cargando…";
  $("#lector-sub").textContent = "";
  $("#texto").innerHTML = "";
  $("#indice").innerHTML = "";
  let p;
  const resaltar = estado.vista ? (window.terminosLector || "") : estado.q;
  try { p = await api(`api/providencia/${id}?q=${encodeURIComponent(resaltar)}`); }
  catch (err) { $("#lector-titulo").textContent = "No se pudo abrir"; $("#texto").textContent = err.message; return; }
  abierta = p;
  const fecha = p.fecha ? new Date(p.fecha + "T12:00").toLocaleDateString("es-CO", { day: "numeric", month: "long", year: "numeric" }) : p.ano;
  $("#lector-titulo").textContent = `${p.tipo} ${p.radicado}`;
  $("#lector-sub").textContent = [p.corte, p.sala, fecha, p.ponente && "M.P. " + p.ponente, p.radicacion && "Radicación " + p.radicacion].filter(Boolean).join(" · ");
  $("#texto").innerHTML = p.html;
  $("#btn-md").href = `api/providencia/${p.id}/md`;
  const fuente = $("#btn-fuente");
  fuente.hidden = !/^https?:/.test(p.url_fuente || "");
  if (!fuente.hidden) fuente.href = p.url_fuente;

  const temas = [p.tema, p.subtema].filter(t => t && !/^Otros|^Sin subtema/.test(t));
  const normas = (p.normas || []).slice(0, 12);
  $("#indice").innerHTML = (p.indice.length ? `<h4>Secciones</h4>` + p.indice.map(s =>
      `<a href="#${esc(s.id)}" class="n${s.nivel}">${esc(s.titulo)}</a>`).join("") : `<h4>Secciones</h4><p class="meta">Sin secciones detectadas</p>`) +
    `<div class="ficha">
      ${temas.length ? `<p><b>Tema:</b> ${esc(temas.join(" › "))}</p>` : ""}
      ${p.resumen ? `<p><b>Síntesis:</b> ${esc(p.resumen)}</p>` : ""}
      ${normas.length ? `<p><b>Normas:</b> ${normas.map(esc).join("; ")}</p>` : ""}
    </div>`;
  $$("#indice a").forEach(a => a.onclick = ev => {
    ev.preventDefault();
    document.getElementById(a.getAttribute("href").slice(1))?.scrollIntoView({ behavior: "smooth" });
  });
  const marcas = resaltarDOM($("#texto"), p.terminos);
  $("#texto").scrollTop = 0;
  if (marcas.length) setTimeout(() => marcas[0].scrollIntoView({ block: "center" }), 50);
  $("#q-texto").value = "";
  $("#q-texto-conteo").textContent = marcas.length ? `${marcas.length} coincidencias` : "";
}

function cerrarLector(actualizarURL = true) {
  if ($("#lector").hidden) return;
  $("#lector").hidden = true;
  document.body.style.overflow = "";
  if (actualizarURL && estado.ver) navegar({ ver: "" });
}

function cita(p) {
  const fecha = p.fecha ? new Date(p.fecha + "T12:00").toLocaleDateString("es-CO", { day: "numeric", month: "long", year: "numeric" }) : p.ano;
  if (p.corte_clave === "cc") {
    const m = /^(T|C|SU|A)-(\d+)[\/-](\d{2,4})$/.exec(p.radicado);
    const nombre = m ? `${m[1]}-${m[2]} de ${p.ano}` : p.radicado;
    return `Corte Constitucional, Sentencia ${nombre} (${fecha}), M.P. ${p.ponente || "—"}.`;
  }
  return `Corte Suprema de Justicia, ${p.sala}, Sentencia ${p.radicado}${p.radicacion ? ` (Radicación ${p.radicacion})` : ""}, ${fecha}, M.P. ${p.ponente || "—"}.`;
}

$("#btn-citar").onclick = async () => {
  if (!abierta) return;
  const texto = cita(abierta);
  try { await navigator.clipboard.writeText(texto); }
  catch { const t = document.createElement("textarea"); t.value = texto; document.body.append(t); t.select(); document.execCommand("copy"); t.remove(); }
  aviso("Cita copiada: " + texto);
};
$("#btn-cerrar").onclick = () => cerrarLector();
$("#lector").addEventListener("click", ev => { if (ev.target.id === "lector") cerrarLector(); });

// Buscar dentro de la sentencia abierta.
let enTexto = [], posicion = -1;
$("#q-texto").addEventListener("input", () => {
  quitarMarcas($("#texto"), "local");
  const v = $("#q-texto").value.trim();
  enTexto = v.length >= 2 ? resaltarDOM($("#texto"), [v], "local") : [];
  posicion = -1;
  $("#q-texto-conteo").textContent = v.length >= 2 ? `${enTexto.length} coincidencias` : "";
  if (enTexto.length) moverEnTexto(1);
});
function moverEnTexto(paso) {
  if (!enTexto.length) return;
  enTexto[posicion]?.classList.remove("activa");
  posicion = (posicion + paso + enTexto.length) % enTexto.length;
  enTexto[posicion].classList.add("activa");
  enTexto[posicion].scrollIntoView({ block: "center" });
  $("#q-texto-conteo").textContent = `${posicion + 1} de ${enTexto.length}`;
}
$("#q-sig").onclick = () => moverEnTexto(1);
$("#q-ant").onclick = () => moverEnTexto(-1);
$("#q-texto").addEventListener("keydown", ev => { if (ev.key === "Enter") { ev.preventDefault(); moverEnTexto(ev.shiftKey ? -1 : 1); } });

document.addEventListener("keydown", ev => {
  if (ev.key === "Escape" && !$("#lector").hidden) cerrarLector();
  if ((ev.ctrlKey || ev.metaKey) && ev.key === "f" && !$("#lector").hidden) { ev.preventDefault(); $("#q-texto").focus(); }
});

// ---------- Controles ----------

$("#form-busqueda").onsubmit = ev => { ev.preventDefault(); navegar({ q: $("#q").value.trim(), pagina: 1, ver: "", vista: "", caso: "" }); };
$("#orden").onchange = () => navegar({ orden: $("#orden").value, pagina: 1 });
["desde", "hasta"].forEach(k => $("#" + k).onchange = () => navegar({ [k]: $("#" + k).value, pagina: 1 }));
$("#limpiar").onclick = () => navegar({ ...Object.fromEntries(FACETAS.map(f => [f, []])), desde: "", hasta: "", pagina: 1 });
$("#btn-ayuda").onclick = () => ($("#ayuda").hidden = !$("#ayuda").hidden);
$("#btn-filtros").onclick = () => $("#filtros").classList.toggle("abierto");

// Se espera a que carguen todos los scripts (casos.js) antes del primer render.
document.addEventListener("DOMContentLoaded", render);
