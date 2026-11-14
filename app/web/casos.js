"use strict";
// Casos, búsqueda de precedentes con IA, usuarios y configuración.
// Usa las utilidades de app.js ($, $$, esc, num, api, navegar, aviso, estado).

let casoActual = null;      // respuesta de api/casos/{id}
let analisisVisible = null; // análisis mostrado en la pestaña de precedentes
let pestana = "sugeridos";
let sondeo = null;
let estadoIA = null;

const SENTIDOS = { favorable: "Favorable", desfavorable: "Desfavorable", mixto: "Mixto", no_aplica: "" };
const NOMBRE_CORTE_CORTO = { csj: "Corte Suprema", cc: "Corte Constitucional" };

async function enviar(metodo, ruta, cuerpo) {
  const r = await fetch(ruta, {
    method: metodo,
    headers: cuerpo ? { "Content-Type": "application/json" } : {},
    body: cuerpo ? JSON.stringify(cuerpo) : undefined,
  });
  const datos = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(datos.detail || r.statusText);
  return datos;
}

const fechaCorta = f => f ? new Date(f.replace(" ", "T")).toLocaleDateString("es-CO", { day: "numeric", month: "short", year: "numeric" }) : "";
const fechaHora = f => f ? new Date(f.replace(" ", "T")).toLocaleString("es-CO", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "";
const fechaLarga = (f, ano) => f ? new Date(f + "T12:00").toLocaleDateString("es-CO", { day: "numeric", month: "long", year: "numeric" }) : (ano || "");
const clave = (corte, radicado) => `${corte}|${radicado}`;

// ---------- Usuarios ----------

function usuarioActual() {
  try { return JSON.parse(localStorage.getItem("buscador.usuario") || "null"); } catch { return null; }
}

function fijarUsuario(u) {
  try { localStorage.setItem("buscador.usuario", JSON.stringify(u)); } catch { /* sin almacenamiento */ }
  window.usuarioMemoria = u;
  pintarUsuario();
}

function usuario() { return usuarioActual() || window.usuarioMemoria || null; }

function pintarUsuario() {
  const u = usuario();
  $("#btn-usuario").textContent = u ? u.nombre : "Elegir usuario";
}

async function pedirUsuario({ obligatorio = false } = {}) {
  const lista = await api("api/usuarios").catch(() => []);
  const modal = $("#modal-usuario");
  return new Promise(resolver => {
    modal.innerHTML = `
      <div class="modal-caja" role="dialog" aria-modal="true" aria-labelledby="titulo-usuario">
        <h2 id="titulo-usuario">¿Quién está usando el buscador?</h2>
        <p class="meta">Cada persona ve sus propios casos. No hay contraseña: es para separar el trabajo, no para protegerlo.</p>
        ${lista.length ? `<div class="lista-usuarios">${lista.map(x => `<button type="button" data-uid="${x.id}">${esc(x.nombre)}</button>`).join("")}</div>` : ""}
        <form id="form-usuario" class="fila">
          <input id="nombre-usuario" placeholder="${lista.length ? "O escribe un nombre nuevo" : "Tu nombre"}" maxlength="60" required>
          <button type="submit" class="primario">${lista.length ? "Agregar" : "Continuar"}</button>
        </form>
        ${obligatorio ? "" : `<button type="button" class="enlace" id="cancelar-usuario">Cancelar</button>`}
      </div>`;
    modal.hidden = false;
    const cerrar = u => { modal.hidden = true; if (u) fijarUsuario(u); resolver(u || null); };
    $$("[data-uid]", modal).forEach(b => b.onclick = () => cerrar(lista.find(x => x.id == b.dataset.uid)));
    $("#form-usuario").onsubmit = async ev => {
      ev.preventDefault();
      try { cerrar(await enviar("POST", "api/usuarios", { nombre: $("#nombre-usuario").value })); }
      catch (err) { aviso(err.message); }
    };
    const cancelar = $("#cancelar-usuario");
    if (cancelar) cancelar.onclick = () => cerrar(null);
    setTimeout(() => $("#nombre-usuario").focus(), 30);
  });
}

async function asegurarUsuario() {
  return usuario() || pedirUsuario({ obligatorio: true });
}

// ---------- Enrutamiento ----------

async function renderVista(vista) {
  if (vista !== "caso") detenerSondeo();
  if (vista !== "linea") detenerSondeoLinea();
  if (vista === "casos") return pintarCasos();
  if (vista === "caso") return pintarCaso(+estado.caso);
  if (vista === "config") return pintarConfig();
  if (vista === "lineas") return pintarLineas();   // lineas.js
  if (vista === "linea") return pintarLinea(+estado.linea);
}

async function cargarEstadoIA() {
  estadoIA = await api("api/ia/estado").catch(() => ({ activa: false }));
  return estadoIA;
}

// ---------- Lista de casos ----------

let verArchivados = false;

async function pintarCasos() {
  const caja = $("#vista-casos");
  const u = await asegurarUsuario();
  if (!u) return;
  caja.innerHTML = `<div class="pagina"><p class="meta">Cargando…</p></div>`;
  const [lista, ia_] = await Promise.all([api(`api/casos?usuario=${u.id}&archivados=${verArchivados}`), cargarEstadoIA()]);
  caja.innerHTML = `
    <div class="pagina">
      <div class="pagina-cabeza">
        <div>
          <h1>${verArchivados ? "Casos archivados" : "Mis casos"}</h1>
          <p class="meta">Describe un caso y el buscador te propone sentencias que pueden servir como precedente.</p>
        </div>
        <div class="acciones">
          <button type="button" class="enlace" id="ver-archivados">${verArchivados ? "Ver casos activos" : "Ver archivados"}</button>
          <button type="button" class="primario" id="nuevo-caso">+ Nuevo caso</button>
        </div>
      </div>
      ${ia_.activa ? "" : `<div class="nota-ia">La búsqueda de precedentes funciona sin IA (por palabras clave), pero con DeepSeek
        identifica el problema jurídico y explica por qué cada sentencia es precedente.
        <a href="?vista=config" data-ir="config">Configurar DeepSeek</a></div>`}
      <div class="lista-casos">
        ${lista.length ? lista.map(c => `
          <a class="tarjeta-caso" href="?vista=caso&caso=${c.id}" data-caso="${c.id}">
            <h3>${esc(c.titulo)}</h3>
            <p>${esc((c.descripcion || "Sin descripción todavía").slice(0, 220))}${c.descripcion.length > 220 ? "…" : ""}</p>
            <div class="meta">${num(c.n_guardadas)} precedente${c.n_guardadas == 1 ? "" : "s"} guardado${c.n_guardadas == 1 ? "" : "s"} ·
              ${num(c.n_analisis)} búsqueda${c.n_analisis == 1 ? "" : "s"} · actualizado ${fechaCorta(c.actualizado)}</div>
          </a>`).join("") : `<div class="vacio">${verArchivados ? "No hay casos archivados." : "Todavía no tienes casos. Crea el primero."}</div>`}
      </div>
    </div>`;
  $("#nuevo-caso").onclick = async () => {
    const c = await enviar("POST", "api/casos", { usuario_id: u.id, titulo: "Caso nuevo" });
    navegar({ vista: "caso", caso: c.id, ver: "" });
  };
  $("#ver-archivados").onclick = () => { verArchivados = !verArchivados; pintarCasos(); };
  $$("[data-caso]", caja).forEach(a => a.onclick = ev => { ev.preventDefault(); navegar({ vista: "caso", caso: a.dataset.caso, ver: "" }); });
  $$("[data-ir]", caja).forEach(a => a.onclick = ev => { ev.preventDefault(); navegar({ vista: a.dataset.ir, ver: "" }); });
}

// ---------- Un caso ----------

async function recargarCaso(id) {
  casoActual = await api(`api/casos/${id}`);
  return casoActual;
}

async function pintarCaso(id) {
  const caja = $("#vista-caso");
  const u = await asegurarUsuario();
  if (!u || !id) return;
  if (!casoActual || casoActual.caso.id !== id) {
    caja.innerHTML = `<div class="pagina"><p class="meta">Cargando caso…</p></div>`;
    try { await recargarCaso(id); } catch (err) { caja.innerHTML = `<div class="pagina"><p>${esc(err.message)}</p></div>`; return; }
    analisisVisible = casoActual.ultimo;
    filtroCuestion = "";
    pestana = "sugeridos";
  }
  await cargarEstadoIA();
  const { caso } = casoActual;
  const ajeno = casoActual.usuario && casoActual.usuario.id !== u.id;
  caja.innerHTML = `
    <div class="pagina caso">
      <div class="pagina-cabeza">
        <div class="titulo-caso">
          <a href="?vista=casos" class="enlace volver" data-ir="casos">‹ Mis casos</a>
          <input id="caso-titulo" class="titulo-editable" value="${esc(caso.titulo)}" maxlength="200" aria-label="Título del caso">
          ${ajeno ? `<p class="meta">Caso de ${esc(casoActual.usuario.nombre)}</p>` : ""}
        </div>
        <div class="acciones">
          <span id="estado-guardado" class="meta"></span>
          <a class="boton" href="api/casos/${caso.id}/informe" download>Exportar informe</a>
          <button type="button" id="archivar">${caso.archivado ? "Reabrir" : "Archivar"}</button>
          <button type="button" id="eliminar" class="peligro">Eliminar</button>
        </div>
      </div>
      <div class="caso-cuerpo">
        <form id="form-caso" class="panel-caso" autocomplete="off">
          <label>Hechos y particularidades del caso
            <textarea id="caso-descripcion" rows="12" placeholder="Cuenta los hechos como se los contarías a un colega: quién es el trabajador o accionante, el tipo de vínculo, qué pasó, fechas aproximadas, pruebas importantes, decisiones previas…">${esc(caso.descripcion)}</textarea>
          </label>
          <label>Lo que se pide o se discute
            <textarea id="caso-pretensiones" rows="4" placeholder="Pretensiones, defensa o pregunta jurídica concreta. Ej.: reintegro por estabilidad laboral reforzada, indemnización de 180 días…">${esc(caso.pretensiones)}</textarea>
          </label>
          <label>Parte que representa
            <select id="caso-posicion">
              <option value="trabajador" ${caso.posicion === "trabajador" ? "selected" : ""}>La parte trabajadora (demandante o accionante)</option>
              <option value="empleador" ${caso.posicion === "empleador" ? "selected" : ""}>La parte empleadora (demandada o accionada)</option>
              <option value="neutral" ${!caso.posicion || caso.posicion === "neutral" ? "selected" : ""}>Ninguna: análisis neutral (juez, estudio)</option>
            </select>
          </label>
          <fieldset>
            <legend>Buscar en</legend>
            <label class="opcion"><input type="checkbox" name="corte" value="csj" ${!caso.cortes.length || caso.cortes.includes("csj") ? "checked" : ""}> Corte Suprema – Sala Laboral</label>
            <label class="opcion"><input type="checkbox" name="corte" value="cc" ${!caso.cortes.length || caso.cortes.includes("cc") ? "checked" : ""}> Corte Constitucional</label>
            <div class="anos">
              <input id="caso-desde" type="number" min="1992" max="2100" placeholder="Desde" value="${caso.desde || ""}" aria-label="Desde el año">
              <span>–</span>
              <input id="caso-hasta" type="number" min="1992" max="2100" placeholder="Hasta" value="${caso.hasta || ""}" aria-label="Hasta el año">
            </div>
            <label class="opcion"><input type="checkbox" id="caso-recientes" ${caso.recientes === 0 ? "" : "checked"}> Dar prioridad a las sentencias recientes</label>
          </fieldset>
          <div class="buscar-precedentes">
            <button type="submit" class="primario grande" id="btn-analizar">Buscar precedentes</button>
            <select id="amplitud" aria-label="Amplitud de la búsqueda">
              <option value="normal">Revisar 40 candidatas</option>
              <option value="amplia">Revisar 80 candidatas (más lento)</option>
            </select>
          </div>
          <p class="meta modo-ia">${estadoIA.activa
            ? `Con IA: ${esc(estadoIA.modelos?.[estadoIA.modelo] || estadoIA.modelo)}. Se envían a DeepSeek los hechos del caso y extractos de las sentencias: <b>no incluyas nombres ni números de identificación</b>.`
            : `Sin IA: búsqueda por palabras clave. <a href="?vista=config" data-ir="config">Configurar DeepSeek</a> para que identifique el problema jurídico y explique cada precedente.`}</p>
        </form>
        <section class="panel-resultados">
          <div class="pestanas" role="tablist">
            <button type="button" role="tab" data-pestana="sugeridos">Precedentes sugeridos</button>
            <button type="button" role="tab" data-pestana="guardados">Guardados <span id="n-guardados"></span></button>
            <button type="button" role="tab" data-pestana="historial">Historial</button>
          </div>
          <div id="contenido-pestana"></div>
        </section>
      </div>
    </div>`;

  // Guardado automático de cada campo.
  const guardarCampo = async cambios => {
    $("#estado-guardado").textContent = "Guardando…";
    try {
      const c = await enviar("PUT", `api/casos/${caso.id}`, { usuario_id: u.id, ...cambios });
      casoActual.caso = c;
      $("#estado-guardado").textContent = "Guardado ✓";
    } catch (err) { $("#estado-guardado").textContent = "No se pudo guardar"; aviso(err.message); }
  };
  const cortesMarcadas = () => $$('#form-caso [name="corte"]:checked').map(x => x.value);
  $("#caso-titulo").onchange = () => guardarCampo({ titulo: $("#caso-titulo").value.trim() || "Caso sin título" });
  $("#caso-descripcion").onchange = () => guardarCampo({ descripcion: $("#caso-descripcion").value });
  $("#caso-pretensiones").onchange = () => guardarCampo({ pretensiones: $("#caso-pretensiones").value });
  $("#caso-posicion").onchange = () => guardarCampo({ posicion: $("#caso-posicion").value });
  $("#caso-recientes").onchange = () => guardarCampo({ recientes: $("#caso-recientes").checked ? 1 : 0 });
  $$('#form-caso [name="corte"]').forEach(x => x.onchange = () => guardarCampo({ cortes: cortesMarcadas().length === 2 ? [] : cortesMarcadas() }));
  ["desde", "hasta"].forEach(k => $(`#caso-${k}`).onchange = () => guardarCampo({ [k]: +$(`#caso-${k}`).value || null }));

  $("#form-caso").onsubmit = async ev => {
    ev.preventDefault();
    if (!cortesMarcadas().length) { aviso("Marca al menos una corte."); return; }
    $("#btn-analizar").disabled = true;
    try {
      await guardarCampo({
        titulo: $("#caso-titulo").value.trim() || "Caso sin título", descripcion: $("#caso-descripcion").value,
        pretensiones: $("#caso-pretensiones").value, cortes: cortesMarcadas().length === 2 ? [] : cortesMarcadas(),
        desde: +$("#caso-desde").value || null, hasta: +$("#caso-hasta").value || null,
        posicion: $("#caso-posicion").value, recientes: $("#caso-recientes").checked ? 1 : 0,
      });
      const { analisis_id } = await enviar("POST", `api/casos/${caso.id}/analizar`, { usuario_id: u.id, amplitud: $("#amplitud").value });
      analisisVisible = { id: analisis_id, estado: "en_curso", progreso: 0, paso: "Iniciando", resultados: [] };
      pestana = "sugeridos";
      pintarPestanas();
      seguirAnalisis(analisis_id);
    } catch (err) {
      aviso(err.message);
      $("#btn-analizar").disabled = false;
    }
  };
  $("#archivar").onclick = async () => {
    await guardarCampo({ archivado: caso.archivado ? 0 : 1 });
    aviso(casoActual.caso.archivado ? "Caso archivado" : "Caso reabierto");
    navegar({ vista: "casos", caso: "" });
  };
  $("#eliminar").onclick = async () => {
    if (!confirm(`¿Eliminar el caso "${caso.titulo}" con sus búsquedas y precedentes guardados? No se puede deshacer.`)) return;
    await enviar("DELETE", `api/casos/${caso.id}`);
    casoActual = null;
    navegar({ vista: "casos", caso: "" });
  };
  $$("[data-ir]", caja).forEach(a => a.onclick = ev => { ev.preventDefault(); navegar({ vista: a.dataset.ir, caso: "", ver: "" }); });
  $$("[data-pestana]", caja).forEach(b => b.onclick = () => { pestana = b.dataset.pestana; pintarPestanas(); });
  pintarPestanas();
  if (analisisVisible?.estado === "en_curso") seguirAnalisis(analisisVisible.id);
}

function pintarPestanas() {
  if (!casoActual) return;
  $$("[data-pestana]").forEach(b => b.setAttribute("aria-selected", b.dataset.pestana === pestana));
  const precedentes = casoActual.guardadas.filter(g => g.estado === "precedente").length;
  $("#n-guardados").textContent = precedentes ? `(${precedentes})` : "";
  const caja = $("#contenido-pestana");
  if (pestana === "guardados") caja.innerHTML = htmlGuardados();
  else if (pestana === "historial") caja.innerHTML = htmlHistorial();
  else caja.innerHTML = htmlSugeridos();
  conectarAcciones(caja);
}

// ---------- Análisis en curso ----------

function detenerSondeo() { if (sondeo) { clearInterval(sondeo); sondeo = null; } }

function seguirAnalisis(aid) {
  detenerSondeo();
  const casoId = casoActual.caso.id;
  sondeo = setInterval(async () => {
    if (estado.vista !== "caso" || +estado.caso !== casoId) { detenerSondeo(); return; }
    let a;
    try { a = await api(`api/analisis/${aid}`); } catch { return; }
    if (a.estado === "en_curso") {
      analisisVisible = a;
      const barra = $("#progreso-analisis");
      if (barra && pestana === "sugeridos") {
        barra.style.width = a.progreso + "%";
        $("#paso-analisis").textContent = a.paso || "";
      } else if (pestana === "sugeridos") pintarPestanas();
      return;
    }
    detenerSondeo();
    await recargarCaso(casoId);
    analisisVisible = a;
    $("#btn-analizar") && ($("#btn-analizar").disabled = false);
    pintarPestanas();
    if (a.estado === "listo") aviso(`Búsqueda terminada: ${a.resultados.length} sentencias revisadas`);
  }, 1500);
}

// ---------- Pestaña: sugeridos ----------

function htmlSugeridos() {
  const a = analisisVisible;
  const lista = casoActual.analisis;
  const selector = lista.length > 1 ? `
    <label class="selector-analisis">Búsqueda:
      <select id="elegir-analisis">${lista.map(x => `<option value="${x.id}" ${a && x.id === a.id ? "selected" : ""}>
        ${fechaHora(x.creado)} · ${x.modo === "ia" ? "con IA" : "sin IA"} · ${x.estado === "error" ? "con error" : x.estado === "en_curso" ? "en curso" : num(x.n) + " revisadas"}</option>`).join("")}
      </select></label>` : "";
  if (!a) {
    return `<div class="vacio">Escribe los hechos del caso y pulsa <b>Buscar precedentes</b>.<br>
      <span class="meta">Mientras más concretos sean los hechos (tipo de vínculo, qué pasó, qué se pide), mejores serán los precedentes.</span></div>`;
  }
  if (a.estado === "en_curso") {
    return `${selector}<div class="progreso">
      <p id="paso-analisis">${esc(a.paso || "Iniciando")}</p>
      <div class="barra-progreso"><div id="progreso-analisis" style="width:${a.progreso || 2}%"></div></div>
      <p class="meta">${a.modo === "local" ? "Unos segundos." : "Con IA tarda entre 1 y 4 minutos (menos cuando las sentencias ya se habían leído en otro caso). Puedes seguir trabajando: el resultado queda guardado en el caso."}</p>
    </div>`;
  }
  if (a.estado === "error") {
    return `${selector}<div class="error-analisis"><b>No se pudo completar la búsqueda.</b><br>${esc(a.error || "")}</div>`;
  }
  if (a.modo === "ia" && a.planteamiento?.version === 2) return selector + htmlAnalisisV2(a);  // analisis.js
  const guardadas = new Map(casoActual.guardadas.map(g => [clave(g.corte_clave, g.radicado), g.estado]));
  const visibles = a.resultados.filter(r => guardadas.get(clave(r.corte_clave, r.radicado)) !== "descartada");
  const conIA = a.modo === "ia";
  const fuertes = conIA ? visibles.filter(r => r.puntaje >= 40) : visibles;
  const debiles = conIA ? visibles.filter(r => r.puntaje < 40) : [];
  const plan = a.planteamiento || {};
  window.terminosLector = (plan.terminos_clave || []).slice(0, 12).map(t => `"${t}"`).join(" ");
  const porRadicado = new Map(a.resultados.map(r => [r.radicado, r]));
  const citar = texto => esc(texto).replace(/\[([^\]]{3,40})\]/g, (m, rad) => {
    const r = porRadicado.get(rad);
    return r && r.id ? `<a href="#" data-ver="${r.id}">[${esc(rad)}]</a>` : m;
  });
  return `${selector}
    ${conIA && plan.problema_juridico ? `<div class="planteamiento">
      <h3>Problema jurídico</h3><p>${esc(plan.problema_juridico)}</p>
      ${plan.asunto_de_fondo ? `<p><b>Asunto de fondo:</b> ${esc(plan.asunto_de_fondo)}</p>` : ""}
      ${(plan.hechos_relevantes || []).length ? `<p><b>Hechos determinantes:</b></p><ul>${plan.hechos_relevantes.map(h => `<li>${esc(h)}</li>`).join("")}</ul>` : ""}
      <details><summary>Búsquedas que hizo</summary><ul class="consultas">${(plan.consultas || []).map(c =>
        `<li><a href="?q=${encodeURIComponent(c.consulta)}" target="_blank" rel="noopener"><code>${esc(c.consulta)}</code></a> ${c.proposito ? `<span class="meta">— ${esc(c.proposito)}</span>` : ""}</li>`).join("")}</ul></details>
    </div>` : ""}
    ${plan.sintesis ? `<div class="sintesis"><h3>Síntesis de la jurisprudencia <span class="meta">(generada con IA: verifícala)</span></h3>
      <p>${citar(plan.sintesis)}</p>
      ${(plan.advertencias || []).length ? `<ul class="advertencias">${plan.advertencias.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}</div>` : ""}
    ${!conIA ? `<div class="nota-ia">Resultados por coincidencia de palabras (sin IA): revisa cada uno.
      Palabras usadas: ${esc((plan.terminos_clave || []).join(", "))}.</div>` : ""}
    <p class="meta">${conIA ? `${num(fuertes.length)} posibles precedentes de ${num(a.resultados.length)} sentencias revisadas` : `${num(visibles.length)} sentencias`}
      · ${fechaHora(a.creado)}${a.tokens_entrada ? ` · ${num(a.tokens_entrada + a.tokens_salida)} tokens` : ""}</p>
    <ol class="lista-precedentes">${fuertes.map(r => htmlPrecedente(r, guardadas, conIA)).join("") || `<li class="vacio">Ninguna candidata resultó ser precedente. Prueba precisando los hechos o ampliando las cortes y los años.</li>`}</ol>
    ${debiles.length ? `<details class="menos"><summary>Menos pertinentes (${debiles.length})</summary>
      <ol class="lista-precedentes">${debiles.map(r => htmlPrecedente(r, guardadas, conIA)).join("")}</ol></details>` : ""}`;
}

function htmlPrecedente(r, guardadas, conIA) {
  const estadoG = guardadas.get(clave(r.corte_clave, r.radicado));
  const nivel = r.puntaje >= 80 ? "alto" : r.puntaje >= 60 ? "medio" : r.puntaje >= 40 ? "bajo" : "minimo";
  const datos = esc(JSON.stringify({ corte_clave: r.corte_clave, radicado: r.radicado, decision: r.decision, regla: r.regla, por_que: r.por_que, puntaje: r.puntaje, sentido: r.sentido }));
  return `<li class="precedente ${r.corte_clave} ${estadoG === "precedente" ? "guardado" : ""}">
    <div class="puntaje ${nivel}" title="Pertinencia de 0 a 100">${r.puntaje}</div>
    <div class="precedente-cuerpo">
      <h4>${r.id ? `<a href="#" data-ver="${r.id}">${esc(r.tipo || "")} ${esc(r.radicado)}</a>` : esc(r.radicado)}
        ${conIA && SENTIDOS[r.sentido] ? `<span class="etiqueta sentido-${r.sentido}">${SENTIDOS[r.sentido]}</span>` : ""}
        ${conIA ? (r.resuelve_fondo ? `<span class="etiqueta fondo">Resuelve el fondo</span>` : `<span class="etiqueta">No resuelve el fondo</span>`) : ""}
        ${conIA ? `<span class="etiqueta" title="Similitud de los hechos con el caso">Hechos ${r.similitud_hechos}/10</span>` : ""}
      </h4>
      <div class="meta">${esc(NOMBRE_CORTE_CORTO[r.corte_clave] || r.corte)} · ${esc(r.sala || "")} · ${esc(fechaLarga(r.fecha, r.ano))}${r.ponente ? " · M.P. " + esc(r.ponente) : ""}</div>
      ${r.decision ? `<p><b>Decisión:</b> ${esc(r.decision)}</p>` : ""}
      ${r.regla ? `<p><b>Regla aplicable:</b> ${esc(r.regla)}</p>` : ""}
      ${r.por_que ? `<p class="${conIA ? "" : "meta"}">${conIA ? "<b>Relación con el caso:</b> " : ""}${esc(r.por_que)}</p>` : ""}
      ${r.fragmento ? `<p class="fragmento">${esc(r.fragmento)}</p>` : ""}
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

// ---------- Pestaña: guardados ----------

function htmlGuardados() {
  const precedentes = casoActual.guardadas.filter(g => g.estado === "precedente");
  const descartadas = casoActual.guardadas.filter(g => g.estado === "descartada");
  const fila = g => {
    const f = g.ficha || {};
    const d = g.datos || {};
    const datos = esc(JSON.stringify({ corte_clave: g.corte_clave, radicado: g.radicado }));
    return `<li class="precedente ${g.corte_clave} guardado">
      ${d.puntaje != null ? `<div class="puntaje ${d.puntaje >= 80 ? "alto" : d.puntaje >= 60 ? "medio" : "bajo"}">${d.puntaje}</div>` : `<div class="puntaje sin">★</div>`}
      <div class="precedente-cuerpo">
        <h4>${g.id ? `<a href="#" data-ver="${g.id}">${esc(f.tipo || "")} ${esc(g.radicado)}</a>` : esc(g.radicado) + ' <span class="meta">(ya no está en la base)</span>'}
          ${SENTIDOS[d.sentido] ? `<span class="etiqueta sentido-${d.sentido}">${SENTIDOS[d.sentido]}</span>` : ""}</h4>
        <div class="meta">${esc(NOMBRE_CORTE_CORTO[g.corte_clave] || "")} · ${esc(f.sala || "")} · ${esc(fechaLarga(f.fecha, f.ano))}${f.ponente ? " · M.P. " + esc(f.ponente) : ""}</div>
        ${d.decision ? `<p><b>Decisión:</b> ${esc(d.decision)}</p>` : ""}
        ${d.regla ? `<p><b>Regla aplicable:</b> ${esc(d.regla)}</p>` : ""}
        ${d.por_que ? `<p><b>Relación con el caso:</b> ${esc(d.por_que)}</p>` : ""}
        <label class="nota">Tus notas
          <textarea rows="2" data-nota="${datos}" placeholder="Por qué te sirve, en qué se diferencia, dónde citarla…">${esc(g.nota)}</textarea></label>
        <div class="acciones-precedente">
          ${g.id ? `<button type="button" data-ver="${g.id}">Ver sentencia</button>` : ""}
          ${g.ficha ? `<button type="button" data-citar="${g.id}">Copiar cita</button>` : ""}
          <button type="button" class="enlace" data-quitar="${datos}">Quitar</button>
        </div>
      </div>
    </li>`;
  };
  return `
    ${precedentes.length ? `<p class="meta">Estos precedentes van en el informe del caso (botón <b>Exportar informe</b>).</p>
      <ol class="lista-precedentes">${precedentes.map(fila).join("")}</ol>`
      : `<div class="vacio">Aún no has guardado precedentes. En <b>Precedentes sugeridos</b> pulsa ☆ <b>Guardar en el caso</b>.<br>
         <span class="meta">También puedes guardar sentencias desde el buscador general.</span></div>`}
    ${descartadas.length ? `<details class="menos"><summary>Descartadas (${descartadas.length})</summary>
      <ul class="descartadas">${descartadas.map(g => `<li>${g.id ? `<a href="#" data-ver="${g.id}">${esc(g.radicado)}</a>` : esc(g.radicado)}
        <button type="button" class="enlace" data-quitar="${esc(JSON.stringify({ corte_clave: g.corte_clave, radicado: g.radicado }))}">Volver a considerar</button></li>`).join("")}</ul></details>` : ""}`;
}

// ---------- Pestaña: historial ----------

function htmlHistorial() {
  const h = casoActual.historial;
  return h.length ? `<ol class="historial">${h.map(x => `<li><span class="meta">${fechaHora(x.fecha)}</span>
      <b>${esc(x.usuario || "—")}</b> ${esc(x.accion.toLowerCase())}${x.detalle ? `: ${esc(x.detalle)}` : ""}</li>`).join("")}</ol>`
    : `<div class="vacio">Sin actividad todavía.</div>`;
}

// ---------- Acciones comunes ----------

function conectarAcciones(caja) {
  const u = usuario();
  const casoId = casoActual.caso.id;
  const actualizar = async (metodo, cuerpo, query = "") => {
    const r = await enviar(metodo, `api/casos/${casoId}/guardadas${query}`, cuerpo);
    casoActual.guardadas = r.guardadas;
    const hist = await api(`api/casos/${casoId}`).catch(() => null);
    if (hist) { casoActual.historial = hist.historial; }
    pintarPestanas();
  };
  $$("[data-ver]", caja).forEach(b => b.onclick = ev => { ev.preventDefault(); navegar({ ver: b.dataset.ver }); });
  $$("[data-guardar]", caja).forEach(b => b.onclick = async () => {
    const d = JSON.parse(b.dataset.guardar);
    const { corte_clave, radicado, ...datos } = d;
    await actualizar("PUT", { usuario_id: u.id, corte_clave, radicado, estado: "precedente", datos });
    aviso(`${radicado} guardada en el caso`);
  });
  $$("[data-descartar]", caja).forEach(b => b.onclick = async () => {
    const { corte_clave, radicado } = JSON.parse(b.dataset.descartar);
    await actualizar("PUT", { usuario_id: u.id, corte_clave, radicado, estado: "descartada" });
    aviso(`${radicado} descartada: no aparecerá en las próximas búsquedas de este caso`);
  });
  $$("[data-quitar]", caja).forEach(b => b.onclick = async () => {
    const { corte_clave, radicado } = JSON.parse(b.dataset.quitar);
    const q = `?usuario_id=${u.id}&corte_clave=${encodeURIComponent(corte_clave)}&radicado=${encodeURIComponent(radicado)}`;
    await actualizar("DELETE", null, q);
  });
  $$("[data-nota]", caja).forEach(t => t.onchange = async () => {
    const { corte_clave, radicado } = JSON.parse(t.dataset.nota);
    await enviar("PUT", `api/casos/${casoId}/guardadas`, { usuario_id: u.id, corte_clave, radicado, estado: "precedente", nota: t.value })
      .then(r => { casoActual.guardadas = r.guardadas; aviso("Nota guardada"); })
      .catch(err => aviso(err.message));
  });
  $$("[data-citar]", caja).forEach(b => b.onclick = async () => {
    const p = await api(`api/providencia/${b.dataset.citar}`);
    const texto = cita(p);
    try { await navigator.clipboard.writeText(texto); } catch { /* sin portapapeles */ }
    aviso("Cita copiada: " + texto);
  });
  conectarAccionesV2(caja);  // analisis.js
  const sel = $("#elegir-analisis", caja);
  if (sel) sel.onchange = async () => {
    analisisVisible = await api(`api/analisis/${sel.value}`);
    pintarPestanas();
    if (analisisVisible.estado === "en_curso") seguirAnalisis(analisisVisible.id);
  };
}

// ---------- Guardar desde el lector (buscador general) ----------

async function guardarDesdeLector() {
  if (!abierta) return;
  const u = await asegurarUsuario();
  if (!u) return;
  const lista = await api(`api/casos?usuario=${u.id}`);
  const modal = $("#modal-usuario");
  modal.innerHTML = `
    <div class="modal-caja" role="dialog" aria-modal="true">
      <h2>Guardar ${esc(abierta.radicado)} en un caso</h2>
      ${lista.length ? `<div class="lista-usuarios">${lista.map(c => `<button type="button" data-a-caso="${c.id}">${esc(c.titulo)}</button>`).join("")}</div>`
        : `<p class="meta">Todavía no tienes casos.</p>`}
      <div class="fila"><button type="button" class="primario" id="caso-nuevo-desde-lector">+ Crear un caso nuevo</button>
      <button type="button" class="enlace" id="cancelar-guardar">Cancelar</button></div>
    </div>`;
  modal.hidden = false;
  const guardarEn = async casoId => {
    await enviar("PUT", `api/casos/${casoId}/guardadas`, { usuario_id: u.id, corte_clave: abierta.corte_clave, radicado: abierta.radicado, estado: "precedente" });
    modal.hidden = true;
    if (casoActual && casoActual.caso.id === casoId) await recargarCaso(casoId);
    aviso(`${abierta.radicado} guardada en el caso`);
  };
  $$("[data-a-caso]", modal).forEach(b => b.onclick = () => guardarEn(+b.dataset.aCaso));
  $("#caso-nuevo-desde-lector").onclick = async () => {
    const c = await enviar("POST", "api/casos", { usuario_id: u.id, titulo: `Caso ${abierta.radicado}` });
    await guardarEn(c.id);
  };
  $("#cancelar-guardar").onclick = () => (modal.hidden = true);
}

// ---------- Configuración ----------

async function pintarConfig() {
  const caja = $("#vista-config");
  const ia_ = await cargarEstadoIA();
  const usuarios = await api("api/usuarios").catch(() => []);
  const u = usuario();
  caja.innerHTML = `
    <div class="pagina estrecha">
      <h1>Configuración</h1>
      <section class="tarjeta-config">
        <h2>Inteligencia artificial (DeepSeek)</h2>
        <p>Estado: ${ia_.activa ? `<b class="ok">Activa</b> · clave terminada en ••••${esc(ia_.clave_final)} · ${esc(ia_.modelos?.[ia_.modelo] || ia_.modelo)}`
          : `<b>No configurada</b>: la búsqueda de precedentes funciona por palabras clave.`}</p>
        ${ia_.puede_configurar ? `
          ${ia_.desde_variable ? `<p class="meta">La clave viene de la variable de entorno DEEPSEEK_API_KEY.</p>` : ""}
          <form id="form-ia" class="form-config" autocomplete="off">
            <label>Clave de API de DeepSeek
              <input id="clave-ia" type="password" placeholder="${ia_.activa ? "Pega una clave nueva para reemplazarla" : "sk-…"}" autocomplete="off" spellcheck="false"></label>
            <label>Modelo
              <select id="modelo-ia">${Object.entries(ia_.modelos || {}).map(([k, v]) => `<option value="${k}" ${k === ia_.modelo ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></label>
            <div class="fila">
              <button type="submit" class="primario">Guardar</button>
              ${ia_.activa ? `<button type="button" id="probar-ia">Probar conexión</button>
              <button type="button" id="quitar-ia" class="enlace peligro">Quitar clave</button>` : ""}
            </div>
            <p id="resultado-ia" class="meta"></p>
          </form>
          <details><summary>Cómo obtener la clave</summary>
            <ol>
              <li>Entra a <b>platform.deepseek.com</b> y crea una cuenta.</li>
              <li>En <b>Top up</b> recarga saldo (es prepago; cada búsqueda de precedentes consume poco).</li>
              <li>En <b>API keys</b> pulsa <b>Create new API key</b>, cópiala y pégala aquí.</li>
            </ol>
            <p class="meta">La clave se guarda solo en este computador (carpeta <code>datos</code> del buscador). Las demás personas que usen el buscador en red aprovechan esta misma clave y no pueden verla ni cambiarla.</p>
          </details>
          <p class="meta"><b>Privacidad:</b> al buscar precedentes con IA se envían a DeepSeek los hechos y pretensiones del caso y extractos de las sentencias candidatas. No escribas en los casos nombres, cédulas ni datos que permitan identificar a las personas.</p>`
          : `<p class="meta">La IA solo se puede configurar en el computador donde corre el buscador.</p>`}
      </section>
      <section class="tarjeta-config">
        <h2>Usuarios</h2>
        <p>Usuario actual: <b>${esc(u?.nombre || "ninguno")}</b> <button type="button" class="enlace" id="cambiar-usuario">Cambiar</button></p>
        <p class="meta">Personas registradas: ${usuarios.map(x => esc(x.nombre)).join(", ") || "ninguna"}.</p>
      </section>
    </div>`;
  $("#cambiar-usuario").onclick = async () => { await pedirUsuario(); pintarConfig(); };
  const form = $("#form-ia");
  if (!form) return;
  const resultado = $("#resultado-ia");
  form.onsubmit = async ev => {
    ev.preventDefault();
    const claveIA = $("#clave-ia").value.trim();
    resultado.textContent = "Guardando…";
    try {
      await enviar("POST", "api/ia/config", { clave: claveIA || null, modelo: $("#modelo-ia").value });
      if (claveIA) {
        resultado.textContent = "Probando la clave con DeepSeek…";
        await enviar("POST", "api/ia/probar");
        aviso("DeepSeek quedó conectado");
      } else aviso("Configuración guardada");
      pintarConfig();
    } catch (err) { resultado.textContent = err.message; }
  };
  const probar = $("#probar-ia");
  if (probar) probar.onclick = async () => {
    resultado.textContent = "Probando…";
    try { const r = await enviar("POST", "api/ia/probar"); resultado.textContent = `Conexión correcta con ${r.modelo}.`; }
    catch (err) { resultado.textContent = err.message; }
  };
  const quitar = $("#quitar-ia");
  if (quitar) quitar.onclick = async () => {
    if (!confirm("¿Quitar la clave de DeepSeek de este computador?")) return;
    await enviar("POST", "api/ia/config", { borrar_clave: true });
    pintarConfig();
  };
}

// ---------- Arranque ----------

$("#btn-usuario").onclick = async () => {
  await pedirUsuario();
  casoActual = null;
  if (estado.vista) navegar({ vista: estado.vista === "caso" ? "casos" : estado.vista, caso: "" }, { reemplazar: true });
};
$$(".menu [data-vista]").forEach(a => a.onclick = ev => {
  ev.preventDefault();
  navegar({ vista: a.dataset.vista, caso: "", linea: "", ver: "" });
});
pintarUsuario();

$("#btn-a-caso").onclick = () => guardarDesdeLector();
