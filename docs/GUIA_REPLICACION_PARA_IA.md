# Especificación técnica para replicar el Descargador de Jurisprudencia colombiana

> **Para quién es este documento.** Lo lee un **agente de IA que programa** (Claude Code u otro equivalente que pueda ejecutar comandos, acceder a internet y usar git). Describe un proyecto que ya funcionó de punta a punta: descargó **39.644 sentencias de la Sala Laboral de la Corte Suprema de Justicia (2012–2026)** y **29.454 sentencias de la Corte Constitucional (1992–2026)**. El objetivo es que construyas una versión **adaptada a las necesidades de jurisprudencia del usuario que te entrega este archivo**, aprovechando todo lo que ya se averiguó y evitando los errores que ya se cometieron.
>
> **Para quién no es.** El usuario final suele ser abogado o abogada, no programador. No le pidas decisiones técnicas que puedas tomar tú; sí pregúntale las decisiones jurídicas y de uso (sección 1).

---

## 0. Instrucciones para el agente (léelas antes de escribir código)

1. **No empieces a programar sin entrevistar al usuario.** Haz las preguntas de la sección 1, en lenguaje no técnico, y espera las respuestas. Si el usuario no sabe algo, propón una opción por defecto razonable y explícale la consecuencia en una frase.
2. **Explora la fuente antes de construir.** Lo descrito aquí sobre las fuentes (secciones 4 y 5) se verificó entre septiembre y noviembre de 2026. Los sitios oficiales cambian. Antes de escribir el descargador completo, haz una prueba en vivo de cada endpoint que vayas a usar: unas pocas solicitudes, no un recorrido masivo. Si algo cambió, investígalo con el método de la sección 12 y avísale al usuario.
3. **Prueba con una muestra pequeña antes del volumen.** Primero entre 5 y 20 documentos de punta a punta (buscar → descargar → convertir → clasificar → guardar → indexar). Muéstrale al usuario 2 o 3 resultados y pregúntale si el formato y la clasificación le sirven. Solo entonces lanza la descarga masiva.
4. **Cuenta el volumen antes de prometer tiempos.** Consulta cuántos documentos hay por año y tipo (solo contar, sin descargar) y dale al usuario una estimación honesta de tiempo y espacio en disco antes de empezar (sección 13).
5. **Persiste en git desde el principio** (sección 3). El entorno donde corres probablemente es efímero. Todo lo que no esté subido a un repositorio remoto se puede perder sin aviso.
6. **Sé respetuoso con los servidores públicos**: una solicitud cada ~1,5 s, reintentos con espera exponencial y ninguna paralelización agresiva. Revisa `robots.txt`.
7. **No pongas datos personales del usuario** (correo, nombre, teléfono) en el *User-Agent* ni en ninguna solicitud a terceros. Usa un identificador genérico del programa (sección 4.7 y 5.3).
8. **No uses una API de IA de pago para clasificar** salvo que el usuario lo pida y confirme que tiene presupuesto. La versión de referencia clasifica con reglas de palabras clave y funciona bien (sección 8).
9. **Informa en lenguaje sencillo.** Cuando termines cada lote, di cuántos documentos van, si hubo errores y qué sigue. Si algo falla, explica qué pasó y si se perdió algo.

---

## 1. Entrevista inicial: lo que debes preguntarle al usuario

Haz estas preguntas al comienzo, de a pocas, sin jerga. Debajo de cada una va el motivo, que es para ti y no tienes que repetirlo.

| # | Pregunta para el usuario | Por qué importa |
|---|---|---|
| 1 | ¿De qué corte o cortes necesitas jurisprudencia? (Corte Constitucional, Corte Suprema —¿qué sala?—, Consejo de Estado, tribunales…) | Define la fuente. Solo la CSJ y la CC están documentadas aquí; cualquier otra requiere fase de exploración (sección 12). |
| 2 | ¿Qué tipo de providencias? ¿Solo sentencias, o también autos? | En la experiencia de referencia, los autos eran más de la mitad del volumen y el usuario los descartó por irrelevantes. Por defecto: solo sentencias. |
| 3 | ¿Qué rango de años? | Determina volumen y tiempo. Ejemplo real: la Sala Laboral tiene ~5.000 sentencias por año en 2018–2021 y ~1.000 por año en 2012–2016. |
| 4 | ¿Qué área o temas te interesan? ¿Quieres que las sentencias se organicen por tema? | Define la taxonomía de clasificación (sección 8). Si la fuente ya trae temas oficiales (la CC sí; la CSJ no), úsalos. |
| 5 | ¿Para qué vas a usar las sentencias? (buscar precedente, alimentar un asistente de IA, hacer fichas, análisis estadístico…) | Define el formato de salida. Para IA: Markdown + JSON de metadatos (sección 7). |
| 6 | ¿Necesitas el PDF o Word original, o basta con el texto? | El original duplica el tiempo y el espacio. Por defecto: solo texto en Markdown, con el original opcional. |
| 7 | ¿Tienes cuenta de GitHub? ¿Quieres que los datos queden en un repositorio público o privado? | Es la forma de que los datos sobrevivan al entorno efímero (sección 3). Las sentencias son públicas, pero el usuario decide. |
| 8 | ¿Tienes presupuesto para una API de IA (para clasificar o resumir), o prefieres que todo funcione gratis? | Por defecto: sin IA de pago. |
| 9 | ¿Cada cuánto vas a necesitar actualizar la base? | El programa se corre manualmente; se puede reenumerar los años recientes para traer solo lo nuevo. |

Cierra la entrevista con un **resumen de una sola pantalla** («Esto es lo que voy a construir: …») y pide confirmación.

---

## 2. Qué construye el proyecto (visión general)

Un programa de línea de comandos en Python que:

1. **Enumera** las providencias de una fuente oficial, año por año y tipo por tipo, guardando la lista para poder retomarla.
2. **Descarga** el texto completo de cada providencia y lo **convierte a Markdown limpio**.
3. **Extrae metadatos**: radicado, corte, sala, tipo, año, fecha, magistrado ponente, normas citadas y URL o ruta de origen.
4. **Clasifica** cada providencia en área → tema → subtema, con la taxonomía oficial de la fuente si existe o con reglas de palabras clave si no.
5. **Guarda** cada providencia como dos archivos (`<RADICADO>.md` y `<RADICADO>_metadata.json`) en carpetas `corte/nivel2/tema/subtema/`.
6. **Indexa** todo en una base SQLite local con búsqueda de texto completo (FTS5). El índice es derivado y se reconstruye a partir de los archivos.
7. **Sube** los archivos a GitHub por lotes, para que no se pierdan.

Diagrama del flujo:

```
Fuente oficial ──► enumerar (lista guardada) ──► por cada radicado nuevo:
   (API / buscador)                                 descargar texto ─► Markdown
                                                    metadatos + clasificación
                                                    escribir .md + .json
                                                    registrar en SQLite (commit inmediato)
                       cada tanda de ≤25 min ──► git add/commit/push
```

El resultado alimenta una fase posterior, que está fuera de este documento: una app o agente de IA de búsqueda de precedente que lee solo los `.md` y `.json`.

---

## 3. Entorno de ejecución: restricciones reales y cómo diseñar para ellas

Estas restricciones se encontraron en la práctica, en Claude Code en la web. Diseña para ellas aunque tu entorno parezca más permisivo.

| Restricción | Qué pasó en el proyecto de referencia | Cómo diseñar |
|---|---|---|
| **Contenedor efímero** | El contenedor se reinició varias veces sin aviso. Una vez se recreó desde cero: se perdieron las dependencias instaladas, los clones de repositorios, los índices y los scripts auxiliares. | Los archivos de datos se suben a git **después de cada tanda**. El índice SQLite se reconstruye solo si falta. Todo debe poder retomarse con el mismo comando. |
| **Límite de ~30 min para tareas en segundo plano** | Una descarga de varias horas fue cortada a los 30 min. | Opción `--max-minutos N` (usa 25): el programa se detiene ordenadamente antes del límite, guarda el avance y termina el log con `ESTADO: COMPLETO` o `ESTADO: INCOMPLETO`. Se relanza el mismo comando hasta que diga COMPLETO. |
| **GitHub rechaza archivos de más de 100 MB** | El índice SQLite llegó a 98 MB con dos años de datos y habría bloqueado el siguiente `push`. | El índice **no se sube a git** (`.gitignore`). Solo se suben `.md` y `.json`, que son la fuente de verdad. Comando `--reconstruir-indice`. |
| **Espacio en disco limitado (~30 GB)** | Con PDF originales, el volumen estimado (~40 GB) no cabía. | Por defecto solo Markdown + JSON (~50–90 KB por providencia). Original opcional (`--con-original`). |
| **GitHub muestra máximo 1.000 archivos por carpeta en la web** | Algunas carpetas de subtema llegaron a 14.000 archivos. | No afecta a git ni a la app, pero avísale al usuario. Para buscar en la web de GitHub: tecla `t` y el radicado. |
| **Repositorio grande** | Se recomienda mantener cada repositorio por debajo de unos pocos GB. | Corpus grandes (p. ej. la CC completa, 2,6 GB en disco) en un **repositorio de datos aparte**, rama propia. |
| **Historial de git** | Al borrar los autos, seguían ocupando espacio en el historial. | Borrar del historial exige reescribirlo (squash + `push --force-with-lease`), y solo con autorización expresa del usuario. Mejor decidir el alcance (autos sí o no) **antes** de descargar. |

### 3.1 Rutina de trabajo por tanda (obligatoria)

```bash
# 1. Lanzar una tanda en segundo plano, con límite de tiempo
python main.py --anio 2020-2012 --max-minutos 25
# 2. Al terminar: revisar errores en el log y confirmar que no hay PDF ni sqlite en el stage
git add jurisprudencia/ estado_enumeracion/
git commit -m "Punto de control: sentencias de <corte> <años> (+N)"
git push -u origin <rama>
# 3. Relanzar el mismo comando hasta que el log diga ESTADO: COMPLETO
```

Crea un script auxiliar (fuera del repo) que haga el paso 2 y reporte el total; lo usarás decenas de veces.

### 3.2 Recuperación tras un reinicio del contenedor

1. `git fetch` y alinear la rama local con la remota (`git merge --ff-only origin/<rama>`).
2. Reinstalar dependencias con el **mismo intérprete** que ejecuta el programa: `python3 -m pip install -r requirements.txt`. Ojo: `pip3` puede apuntar a otra versión de Python.
3. Volver a clonar los repositorios de datos aparte, en la rama correcta.
4. Relanzar: el programa reconstruye el índice SQLite si no existe y salta lo ya descargado.

---

## 4. Fuente 1: Corte Suprema de Justicia (API GraphQL no documentada)

### 4.1 Cómo se descubrió

- Buscador público: `https://consultaprovidencias.cortesuprema.gov.co/` (SPA en React). El HTML solo trae `<div id="app">` y `/bundle.js`, así que no se puede raspar con `requests` + BeautifulSoup.
- Descargando `bundle.js` y buscando URLs (`grep -oE "https?://..."`) aparece el backend: **`https://consultaprovidenciasbk.cortesuprema.gov.co`**, con las rutas `/api` (GraphQL), `/downloadFile`, `/fileExists`, `/filters` y `/accessLog`.
- Las consultas GraphQL están escritas como *template strings* dentro del bundle. No hay variables GraphQL: el valor se interpola directamente en la consulta, así que **escapa** `\`, `"` y saltos de línea.
- No requiere autenticación ni tiene captcha. `robots.txt` no existe en el subdominio (la SPA devuelve `index.html` para cualquier ruta).

### 4.2 Búsqueda: `getSearchResult`

`POST https://consultaprovidenciasbk.cortesuprema.gov.co/api` con `Content-Type: application/json` y cuerpo `{"query": "<consulta>"}`:

```graphql
{
  getSearchResult(searchQuery:{
    query: "de"              # texto obligatorio (ver 4.4)
    typeOfQuery: "LABORAL"   # sala
    start: 0                 # desplazamiento; 10 resultados por página
    isExact: false
    magistrate: ""
    year: "2024"
    autoSentencia: "SENTENCIA"   # "SENTENCIA" | "AUTO" | "" (ambos)
    order: "NEW_FIRST"           # "NEW_FIRST" | "OLD_FIRST" | ""
    roomTutelas: ""
    addedQueries: []
  }) {
    searchResults { title id ano fechaCreacion autoSentencia doctor leyesOArticulos fiveParaphraseResult onlinePath }
    numOfResults
  }
}
```

**Valores de `typeOfQuery` verificados en vivo (noviembre de 2026, año 2024, solo sentencias):**

| `typeOfQuery` | Resultado | Estructura del `id` (ruta interna) |
|---|---|---|
| `LABORAL` | ✅ 7.272 resultados en bruto | `/var/www/html/Index/LABORAL/{PERMANENTE\|DESCONGESTION}/2024/Dr. X/Sentencias/SL2981-2024.pdf` |
| `CIVIL` | ✅ 216 | `/Index/CIVIL/2024/Dr. X/12.- Diciembre/Sentencias/SC3…` (incluye carpeta de mes) |
| `PENAL` | ✅ 806 | `/Index/PENAL/2024/Dr. X/Sentencia/SP918-2024(56228).docx` (el radicado incluye el número de proceso entre paréntesis) |
| `TUTELAS` | ✅ 28.273 | `/Index/TUTELAS/PENAL/2024/Reserva/Dr. X/Sentencias/STP…` (sub-sala en la ruta: CIVIL/LABORAL/PENAL) |
| `PLENA` | ❌ devuelve `null` | — |

- **Campos útiles:** `title` (nombre del archivo, p. ej. `SL208-2026.pdf`), `id` (ruta interna, idéntica a `onlinePath`; es la clave para pedir el contenido), `ano` (año de la **carpeta**, no siempre correcto, ver 4.6), `fechaCreacion` (fecha del **archivo** en el servidor, **no** la fecha del fallo), `autoSentencia`, `doctor` (magistrado ponente), `leyesOArticulos` (normas citadas, extraídas por la Corte).
- **No hay tema ni subtema oficial**: hay que clasificar por reglas (sección 8).
- **El filtro `roomTutelas` no separa sub-salas en `LABORAL`**: devuelve lo mismo con `PERMANENTE` y con `DESCONGESTION`. La sub-sala se deduce del `id` (`/LABORAL/DESCONGESTION/` o `/LABORAL/PERMANENTE/`). Para otras salas, inspecciona la estructura de rutas y deduce la sub-sala de la misma manera.
- La búsqueda vacía (`query: ""`) devuelve 0 resultados.

### 4.3 Texto completo: `getContentSearch`

```graphql
{
  getContentSearch(previewDocument:{
    id: "<id del resultado>"
    room: "LABORAL"
    text: "de"          # ¡OBLIGATORIO NO VACÍO! (ver abajo)
  }) { contentText title onlinePath }
}
```

- `contentText` es el **texto completo ya extraído, en HTML**: párrafos `<p>`, títulos `<div class="centered-title"><h2 class="tittle-document">…</h2></div>` y resaltados `<mark>`. No hace falta procesar el PDF.
- ⚠️ **Con `text: ""` solo devuelve los títulos de sección** (~350 caracteres). Con cualquier término (p. ej. `"de"`) devuelve el texto completo (~40.000 caracteres), pero envuelve cada coincidencia en `<mark>…</mark>`. Hay que hacer **`unwrap()` de los `<mark>`** antes de convertir a Markdown.
- Conversión: BeautifulSoup → `mark.unwrap()` y `div.centered-title.unwrap()` → `markdownify(html, heading_style="ATX", bullets="-")` → colapsar espacios y saltos triples. Cada `<p>` es una línea del PDF, no un párrafo; es aceptable para RAG.

### 4.4 Enumeración: cómo listar «todas» las providencias de un año

No existe un modo «traer todo». La solución que funcionó:

- `query: "de"` (aparece en prácticamente toda providencia en español), `year`, `autoSentencia`, y paginar `start = 0, 10, 20, …` mientras `start < numOfResults`.
- `numOfResults` cuenta **archivos**, no providencias: la misma providencia suele aparecer como `.pdf` y como `.doc`/`.docx`. **Deduplica por radicado** (título sin extensión) y **prefiere la entrada `.pdf`**. En la práctica, de 2 a 4,5 resultados en bruto equivalen a una providencia.
- **Guarda el avance de la enumeración** en un archivo (`estado_enumeracion/<año>-<tipo>-<sala>.json`, con `completa`, `siguiente_start`, `total` y `documentos`) cada 20 páginas, y súbelo a git. Enumerar un año grande toma 25–50 min (1.000–1.600 páginas × 1,5 s). Sin esto, cada tanda empezaría de cero.
- Una enumeración marcada `completa` no se repite. Para años recientes, en los que la Corte sigue publicando, ofrece `--reenumerar`.

### 4.5 Descarga del original: `/downloadFile`

`POST /downloadFile` con JSON `{"path": "<id>"}` devuelve el binario (PDF o Word). Es opcional (`--con-original`). Para documentos antiguos a veces da 404: el archivo ya no existe en el servidor aunque siga en el índice del buscador.

### 4.6 Particularidades de los datos (errores de la fuente)

- **Año de carpeta equivocado**: 100 sentencias de 2019 venían en la carpeta `2009`, así que `ano` = 2009. Si el usuario filtra por año, adviérteselo.
- **Duplicados entre sub-salas**: un mismo radicado (p. ej. `AL7696-2024`) apareció en PERMANENTE y en DESCONGESTION. La clave única debe ser `(corte, radicado, sub_sala)`.
- **Autos con texto incompleto**: muchos autos solo tienen publicada la constancia de notificación y ejecutoria (~600 caracteres) y no el texto del auto. Detéctalos (`"constancia de notificacion"` y longitud < 1.500) y márcalos aparte. No se pueden recuperar por esta vía.
- **Timeouts esporádicos** del backend (lecturas de 30 s, desconexiones del proxy): los reintentos con backoff los resolvieron siempre en el intento siguiente o en la tanda siguiente.
- **Publicación con retraso**: en noviembre de 2026 el buscador tenía 1.390 sentencias laborales de 2025 y 43 de 2026, frente a ~2.900–5.000 de años anteriores. No es un error del descargador.
- **Prefijos de radicado**: `SL` sentencia laboral, `AL` auto laboral, `SC` sentencia civil, `SP` sentencia penal, `STP`/`STC`/`STL` tutelas.

### 4.7 Parámetros de cortesía usados

`User-Agent: DescargadorSentenciasCSJ/0.1 (uso academico/personal)` (sin datos personales). Pausa de 1,5 s entre solicitudes, 5 reintentos con backoff de 2, 4, 8 y 16 s ante errores de red, 429 o 5xx, y timeout de 30 s.

### 4.8 Rendimiento real

~830 sentencias por tanda de 25 min (1 solicitud por sentencia sin original). La Sala Laboral 2012–2026 (39.644 sentencias) tomó unas 50 tandas en total, incluidas las enumeraciones.

---

## 5. Fuente 2: Corte Constitucional (buscador de la Relatoría, HTML)

### 5.1 Endpoints

Base: `https://www.corteconstitucional.gov.co/relatoria/buscador_new/index.php`. Es HTML plano, sin JavaScript necesario. `robots.txt` permite `/relatoria/`.

**a) Enumeración por faceta tipo + año (`accion=searchByAggs`, POST form-urlencoded):**

```python
data = {
    "searchOption": "texto", "buscar_por": "",
    "finicio": "1992-01-01", "ffin": f"{anio}-12-31",
    "ver_formulario": "si", "volver_a": "relatoria",
    "OrderbyOption": "des__score",
    "cant_providencias": 5000, "maxprov": 5000,
    "accion": "searchByAggs",
    "aggs_prov_tipo[]": f"prov_tipo|{ETIQUETA}|0",
    "aggs_prov_f_sentencia[]": f"prov_f_sentencia|{anio}|0",
}
```

- Etiquetas exactas de `prov_tipo`: `Tutela`, `Constitucionalidad`, `Sentencia de unificación`, `Auto`.
- Una sola solicitud trae hasta **5.000** resultados (ningún año/tipo de sentencia supera ese tope; los autos de 2023 llegaron a 3.120).
- Resultados en `<table id="tablet_results"><tbody><tr>`: celda 0 con `<input type="hidden" value="<prov_id>">` y `<a title="Ver providencia" href=".../relatoria/2019/T-621-19.htm">T-621/19</a>`; celda 1 con la fecha de la sentencia; celda 2 con `TEMA: … RESUMEN: …`; celda 3 con la fecha de publicación.
- El radicado se toma del nombre del archivo en el `href` (`T-621-19`, `SU418-19`, `C-447-92`).
- Para ver cuántos hay por tipo en un año: buscar solo con la faceta del año y leer el arreglo JavaScript `var AggsArray = [...]` del HTML (`"prov_tipo|Tutela|364|0"`).

**b) Temas oficiales («titulaciones»):** POST `{"prov_id": "<id>", "accion": "ver_titulacionesXIDprovidencia"}` → `<table id="tablet_titulaciones">`, con filas *Tema (descriptor) | Subtema (restrictor)*. Una providencia puede tener muchas filas; se usó la **primera** como tema/subtema principal y se guardaron todas en el JSON.

**c) Texto:** GET al `href` `.htm`. Viene codificado en `windows-1252` (leer el `charset` del `<meta>`). Se quitan `script`, `style` y `head` y se pasa por `markdownify`. Las líneas partidas por el HTML de Word se unen por bloque.

**d) Ficha de detalle (opcional, no usada):** POST `{"prov_sentencia": "<numero>", "accion": "ver_modal_detalle_providencia"}` → expediente, fechas, ponentes, salvamentos y resuelve.

### 5.2 Particularidades verificadas

- **Huecos en la numeración**: p. ej. la T-017/19 no aparece en el buscador. Su `.htm` existe pero es una **página genérica de ~8,6 KB** sin contenido. Hay que detectarla (respuesta de < 20 KB con < 200 caracteres de texto) y omitirla. El buscador sí lista todo lo publicado.
- **Años sin sentencias de unificación** en el buscador: 2004 y 1992 no tienen esa faceta. No es un error.
- **Sentencias recientes sin titulación**: la Relatoría tarda en asignar temas; ~0,2% quedaron sin tema oficial.
- **Magistrado ponente**: no hay campo estructurado en el listado. Se extrae del texto: (1) la etiqueta `Magistrado(a) Ponente:` / `Magistrado(a) sustanciador(a):`, tomando las palabras siguientes en mayúsculas o con mayúscula inicial y cortando en «Bogotá», «Aprobado», «Referencia», etc.; (2) en su defecto, la firma al final del texto (`NOMBRE EN MAYÚSCULAS` + `Magistrado Ponente|Presidente`). Así quedó sin identificar el ~10%, sobre todo en los años noventa. Es mejorable.
- **Normas citadas**: regex `\b(Ley|Decreto(?:\s+Ley)?|Acto\s+Legislativo)\s+(\d{1,4})\s+de\s+(\d{4})\b`, deduplicadas y limitadas a 40.
- **Sala**: tutela → Sala de Revisión; C y SU → Sala Plena; autos → «Sala Especial de Seguimiento» o «Revisión» según el encabezado.
- **«Exportar a Excel» está bloqueado** por el cortafuegos del sitio (HTTP 500 «The URL you requested has been blocked»).

### 5.3 Reglas del cortafuegos (WAF) — críticas

- El *User-Agent* **debe empezar por un token de navegador** (`Mozilla/5.0 (…)`) y **no puede contener la subcadena `CCBot`**. Si no, responde HTTP 500. Valor que funcionó: `Mozilla/5.0 (compatible; DescargadorJurisprudencia/0.1; investigacion academica)`.
- **No repitas un mismo campo de formulario** (p. ej. dos `aggs_prov_tipo[]` en una solicitud): bloquea por *parameter pollution*. Haz **una consulta por cada combinación (tipo, año)**.

### 5.4 Rendimiento real

~400 sentencias por tanda de 25 min (2 solicitudes cada una: `.htm` + titulaciones). Las 29.454 sentencias de 1992–2026 tomaron unas 75 tandas.

---

## 6. Algoritmo del pipeline (pseudocódigo)

```text
ejecutar(anios, tipos, max_minutos, limite, reenumerar):
    presupuesto = Presupuesto(max_minutos)           # lanza TiempoAgotado al vencer
    si no existe indice.sqlite y hay *_metadata.json: reconstruir_indice()
    inicializar esquema SQLite
    para anio en anios:                              # admitir rangos descendentes "2026-1992"
        para tipo en tipos:
            lista = enumerar(anio, tipo)             # retoma o reutiliza estado_enumeracion/
            para doc en lista:
                si limite alcanzado: parar (INCOMPLETO)
                presupuesto.verificar()
                si (corte, radicado, sub_sala) ya está en el índice: saltar
                try:
                    texto_html = obtener_contenido(doc)
                    markdown   = limpiar_y_convertir(texto_html)
                    clasif     = clasificar(markdown, metadatos)      # o temas oficiales
                    carpeta    = raiz/corte/nivel2/slug(tema)/slug(subtema)
                    escribir <RADICADO>.md (encabezado + "\n---\n\n" + cuerpo)
                    escribir <RADICADO>_metadata.json
                    registrar en SQLite (+ FTS con rowid = id)
                    conn.commit()                    # ¡inmediato, no al final!
                except Exception: log y continuar
    log "ESTADO: COMPLETO" o "ESTADO: INCOMPLETO …"
```

Puntos clave:

- **Commit de SQLite después de cada documento.** La primera versión solo hacía commit al final, y una tanda cortada perdía el registro de todo lo descargado (los archivos quedaban huérfanos).
- **Un error en un documento no detiene la tanda**: se registra y se sigue. La siguiente tanda lo reintenta, porque no quedó en el índice.
- **`reconstruir_indice()`** borra el `.sqlite` y lo regenera desde los `.json` y `.md` (separando encabezado y cuerpo por la primera aparición de `"\n---\n\n"`). Tarda ~1 min por cada 30.000 documentos.
- **`reclasificar()`** vuelve a aplicar las reglas a todo lo descargado sin consultar la fuente: mueve los archivos a la carpeta nueva, actualiza el JSON, el encabezado del `.md` y el índice, y borra las carpetas vacías.

---

## 7. Contrato de datos (formato común para todas las cortes)

Este formato permitió unificar la CSJ y la CC. **Respétalo**, aunque agregues campos propios, para que una app posterior pueda leer cualquier corte.

### 7.1 Estructura de carpetas

```
jurisprudencia/
  <corte-slug>/                 # corte-suprema-sala-laboral, corte-constitucional, ...
    <nivel-2-slug>/             # sub-sala (CSJ) o área del derecho (CC)
      <tema-slug>/
        <subtema-slug>/
          <RADICADO>.md
          <RADICADO>_metadata.json
  indice.sqlite                 # local, NO va a git
estado_enumeracion/             # avance de enumeraciones, SÍ va a git
```

Slug: NFKD → ASCII, minúsculas, `[^a-z0-9]+` → `-`, sin guiones al borde, **recortado a 60 caracteres** (los descriptores oficiales de la CC superan los 200 caracteres y Windows limita la ruta a 260). La app **nunca** debe deducir datos de la ruta: todo va en el JSON.

### 7.2 `<RADICADO>_metadata.json` (UTF-8, `ensure_ascii=False`, indentado con 2 espacios)

| Campo | Tipo | Notas |
|---|---|---|
| `radicado` | str | Igual al nombre del archivo, sin espacios: `SL208-2026`, `T-388-19`, `SU418-19` |
| `corte` | str | Nombre exacto: `"Corte Suprema de Justicia"`, `"Corte Constitucional"` |
| `sala` | str | CSJ: `"LABORAL"`. CC: `"PLENA"`, `"REVISION"` o `"SEGUIMIENTO"` |
| `sub_sala` | str | CSJ: `"PERMANENTE"`/`"DESCONGESTION"`; si no aplica, igual a `sala`. **Nunca vacío** (forma parte de la clave única) |
| `tipo_providencia` | str | `"SENTENCIA"` o `"AUTO"` |
| `ano` | int | Año de la providencia según la fuente |
| `fecha_creacion` | str\|null | CSJ: fecha del archivo en el servidor (no la del fallo). CC: fecha de la sentencia |
| `magistrado_ponente` | str\|null | |
| `area` | str | Área del derecho; para lo laboral usa exactamente `"Derecho Laboral y Seguridad Social"` |
| `tema`, `subtema` | str | `"Otros - Sin clasificar"` / `"Sin subtema"` cuando no hay |
| `puntaje_clasificacion` | int\|null | Coincidencias de palabras clave; `null` si el tema es oficial |
| `leyes_o_articulos` | list[str] | Puede ser `[]` |
| `doc_id_origen` | str | Ruta interna (CSJ) o URL (CC) |
| `fecha_descarga` | str | ISO 8601 UTC |
| *(opcionales CC)* | | `fuente_clasificacion`, `fecha_providencia`, `fecha_publicacion`, `numero`, `tipo_cc`, `prov_id`, `tema_relatoria`, `resumen`, `titulaciones` |

### 7.3 `<RADICADO>.md`

```markdown
# SL208-2026

- **Corte:** Corte Suprema de Justicia
- **Sala:** Sala de Casación Laboral
- **Magistrado ponente:** Dr. Juan Carlos Espeleta Sanchez
- **Fecha:** 2026-04-28T12:58:21Z
- **Tipo de providencia:** SENTENCIA
- **Tema:** Pensiones
- **Subtema:** Régimen de transición y RAIS/RPM
- **Normas citadas:** Decreto 758 de 1990, Ley 100 de 1993

---

(texto completo en Markdown)
```

El separador `\n---\n\n` debe ser la **primera** aparición de esa secuencia en el archivo.

### 7.4 Índice SQLite (derivado, local)

```sql
CREATE TABLE IF NOT EXISTS providencias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    corte TEXT NOT NULL, sala TEXT NOT NULL, sub_sala TEXT NOT NULL,
    tipo_providencia TEXT, radicado TEXT NOT NULL, ano INTEGER,
    fecha_creacion TEXT, magistrado_ponente TEXT, area TEXT, tema TEXT, subtema TEXT,
    puntaje_clasificacion INTEGER, leyes_o_articulos TEXT,   -- JSON
    doc_id_origen TEXT NOT NULL, ruta_markdown TEXT, ruta_original TEXT,
    ruta_metadata TEXT, fecha_descarga TEXT NOT NULL,
    UNIQUE (corte, radicado, sub_sala)
);
CREATE INDEX IF NOT EXISTS idx_providencias_tema ON providencias (tema, subtema);
CREATE INDEX IF NOT EXISTS idx_providencias_ano ON providencias (ano);
-- rowid de providencias_fts = providencias.id
CREATE VIRTUAL TABLE IF NOT EXISTS providencias_fts USING fts5(
    radicado, tema, subtema, texto_completo,
    tokenize='unicode61 remove_diacritics 2'
);
```

- ⚠️ **No uses una tabla FTS «contentless» (`content=''`) sin fijar el `rowid`**: la primera versión lo hizo y la búsqueda devolvía coincidencias sin poder decir de qué providencia eran. Inserta con `rowid = providencias.id`.
- `remove_diacritics 2` permite buscar `pension` y encontrar «pensión».
- `sqlite3.connect(..., timeout=60)` y `PRAGMA journal_mode=WAL` (lectores concurrentes mientras se descarga).
- Para consultar por radicado, filtra también por `corte` (la clave única empieza por `corte`); si no, la consulta no usa el índice y es muy lenta.

Consulta de ejemplo:

```sql
SELECT p.corte, p.radicado, p.tema, p.ruta_markdown
FROM providencias_fts f JOIN providencias p ON p.id = f.rowid
WHERE providencias_fts MATCH 'estabilidad reforzada' ORDER BY rank LIMIT 20;
```

---

## 8. Clasificación

### 8.1 Si la fuente trae temas oficiales (caso CC)

Úsalos tal cual para `tema`/`subtema` y guarda todas las titulaciones en el JSON. Agrega solo un **nivel superior de área**, asignado por reglas de palabras clave sobre las titulaciones, el TEMA y el RESUMEN. Busca **palabras completas** (`\bpos\b`), no subcadenas: con subcadenas, «pos» coincidía con «posible». Reglas de desempate: gana el área con más coincidencias; ante empate, la primera de la lista; sin coincidencias, `Control de Constitucionalidad Abstracto` si es tipo C y `Otros - Sin clasificar` en los demás casos.

Áreas usadas en la CC: Derechos Fundamentales y Debido Proceso · Control de Constitucionalidad Abstracto · Derecho Laboral y Seguridad Social · Derecho de Familia y Derechos de Niños, Niñas y Adolescentes · Derecho Penal y Sistema Acusatorio · Derecho Administrativo y Función Pública · Derecho Constitucional Económico · Derechos Étnicos y Consulta Previa · Derecho a la Salud · Otros - Sin clasificar.

### 8.2 Si la fuente no trae temas (caso CSJ): reglas de palabras clave

- Estructura de datos: `TAXONOMIA = {tema: {subtema: [frases clave]}}`. El texto y las frases se normalizan (minúsculas, sin tildes) y se cuentan las apariciones con `str.count` (más rápido que regex: ~4 ms por documento).
- Puntaje del tema = suma de sus subtemas, más un bono de +3 por norma citada asociada al tema (`NORMA_A_TEMA`, p. ej. `"ley 100 de 1993" → Pensiones`). Gana el tema con más puntos y, dentro de él, el subtema con más puntos.
- **Respaldo de «Trámite procesal»**: si ningún tema de fondo coincide, se prueban subtemas procesales (deserción del recurso, desistimiento, conflictos de competencia, admisión/rechazo, nulidades, costas, aclaración/adición, recursos contra autos, sucesión procesal, impedimentos, transacción, acumulación, revisión, medidas cautelares). Es esencial si se descargan autos: sin él, el 15% de los autos quedaba sin clasificar; con él, el 0,1%.
- Si tampoco calza: «Texto incompleto en la fuente» (constancias de notificación) u «Otros - Sin clasificar».
- Resultado real en la Sala Laboral: solo 43 de 39.644 sentencias quedaron sin clasificar.

Taxonomía laboral usada (temas y subtemas):

- **Contrato de Trabajo y Contrato Realidad:** contrato realidad y subordinación; tipos de contrato y vinculación; contrato de trabajo (general).
- **Pensiones:** vejez; invalidez; sobrevivientes; régimen de transición y RAIS/RPM.
- **Seguridad Social en Salud y Riesgos Laborales:** salud (EPS); riesgos laborales/ARL.
- **Estabilidad Laboral Reforzada y Fuero:** fuero de salud/debilidad manifiesta; fuero de maternidad; fuero sindical.
- **Terminación del Contrato, Despido e Indemnizaciones:** sin justa causa; justa causa y terminación unilateral; renuncia.
- **Salario, Prestaciones Sociales e Indemnización Moratoria:** salario y factores salariales; prestaciones sociales; indemnización moratoria.
- **Derecho Colectivo del Trabajo:** laudos arbitrales y recurso de anulación; convenciones y pactos; sindicatos y negociación; huelga.
- **Prescripción y Caducidad.**
- **Aspectos Procesales del Recurso de Casación Laboral:** técnica de casación; admisibilidad y procedencia.

### 8.3 Cómo construir la taxonomía para otra área

1. Pídele al usuario sus 8–12 temas principales y, por cada uno, 2–4 subtemas, **con las expresiones que usarían los jueces** (no términos académicos).
2. Agrega las normas emblemáticas de cada tema (`NORMA_A_TEMA`).
3. Descarga una muestra de ~50–100 documentos, clasifica y muéstrale al usuario el reparto y 5 ejemplos de «Otros». Ajusta las frases.
4. Después de la descarga masiva, puedes ajustar las reglas y correr `--reclasificar` sin volver a descargar nada.
5. Recuerda: las reglas fallan en los casos mixtos (se asigna el tema con más coincidencias). El usuario debe saber que la clasificación es orientativa.

Puntos de partida sugeridos para otras áreas (valídalos con el usuario):

- **Familia / NNA:** custodia y cuidado personal, alimentos, visitas, filiación/paternidad, adopción, divorcio y cesación de efectos civiles, unión marital y sociedad patrimonial, violencia intrafamiliar, restablecimiento de derechos (ICBF), sucesiones.
- **Civil / responsabilidad:** responsabilidad contractual, extracontractual, médica, por actividades peligrosas; daño (material, moral, a la vida de relación); nexo causal; seguros; prescripción.
- **Inmobiliario:** compraventa, promesa de contrato, arrendamiento, propiedad horizontal, posesión y prescripción adquisitiva, reivindicatorio, servidumbres, lesión enorme.
- **Administrativo:** nulidad y restablecimiento, reparación directa, controversias contractuales, contratación estatal (licitación, liquidación, incumplimiento), carrera administrativa, responsabilidad del Estado.
- **Ambiental / tierras:** licencias ambientales, consulta previa, restitución de tierras (Ley 1448 de 2011), baldíos, derecho al agua, áreas protegidas.
- **Migratorio:** nacionalidad, PEP/PPT, expulsión, refugio, acceso a salud de migrantes, apatridia.

### 8.4 Clasificación con IA (solo si el usuario tiene presupuesto)

Puede mejorar los casos mixtos y extraer hechos, *ratio decidendi* y normas, pero cuesta por documento y puede equivocarse (confundir *obiter* con *ratio*). Si se usa: hazlo **después** de la descarga, como paso separado y reanudable; estima el costo con una muestra; guarda el resultado en campos nuevos del JSON (no reemplaces los de reglas); y deja claro que requiere verificación humana.

---

## 9. Interfaz de línea de comandos (CLI)

```bash
pip install -r requirements.txt            # requests, beautifulsoup4, markdownify
python main.py --anio 2024 --limite 20     # prueba pequeña
python main.py --anio 2015-2024            # rango (también descendente: 2024-2015)
python main.py --anio 2024 --tipo SENTENCIA
python main.py --anio 2020-2012 --max-minutos 25   # tandas que se detienen solas
python main.py --anio 2026-2025 --reenumerar       # traer lo nuevo de años recientes
python main.py --con-original              # también PDF/Word
python main.py --reconstruir-indice        # regenerar SQLite desde los archivos
python main.py --reclasificar              # reaplicar reglas sin descargar
python main.py --corte constitucional --anio 2026-1992 --max-minutos 25
```

Opciones: `--corte`, `--anio`, `--tipo` (repetible), `--limite`, `--forzar`, `--con-original`, `--max-minutos`, `--reenumerar`, `--reclasificar`, `--reconstruir-indice` y `--verboso`. Por defecto **no se descargan autos** (se piden con `--tipo AUTO` o `--tipo A`).

---

## 10. Estructura de código de referencia

```
main.py                       # agrega src/ al path y llama cli.main()
requirements.txt
src/csj_scraper/
  config.py                   # URLs, User-Agent, pausas, salas, rutas
  api_client.py               # GraphQL: search, get_full_content, download_file (+reintentos)
  html_to_markdown.py         # unwrap <mark>, markdownify, limpieza
  taxonomy.py                 # TAXONOMIA, TRAMITE_SUBTEMAS, NORMA_A_TEMA, clasificar()
  db.py                       # esquema, conectar(), registrar_providencia(), FTS rowid=id
  pipeline.py                 # Presupuesto, enumerar_radicados(), procesar_documento(),
                              # ejecutar(), reconstruir_indice(), reclasificar()
  utils.py                    # slugify, radicado_desde_titulo
  cli.py                      # argparse; despacha a csj o cc
src/cc_scraper/
  config.py, cliente.py       # WAF-friendly UA, reintentos
  relatoria.py                # searchByAggs, titulaciones, .htm → Markdown, ponente, normas
  areas.py                    # reglas de área (palabra completa)
  pipeline.py                 # mismo patrón; escribe en el repo de datos aparte
docs/
  ESPECIFICACION_UNIFICACION.md   # contrato de datos común
.gitignore                    # *.pdf, *.doc(x), indice.sqlite*, estado_enumeracion/*.tmp
```

---

## 11. Lecciones aprendidas: errores que no debes repetir

1. **Prometer tiempos sin contar.** La primera estimación fue de horas; la real, decenas de horas. Cuenta primero (sección 13).
2. **Guardar datos fuera de git** en un entorno efímero.
3. **Hacer commit en SQLite solo al final** de la corrida.
4. **Subir el índice SQLite** a git (límite de 100 MB).
5. **FTS contentless sin `rowid`** (sección 7.4).
6. **Lanzar procesos con `nohup … &`** dentro de una tarea en segundo plano: el sistema da la tarea por terminada al instante y no avisa al final. Lanza el comando directamente como tarea en segundo plano.
7. **Clasificar con subcadenas** en vez de palabras completas.
8. **Llamar `getContentSearch` con `text` vacío** (solo devuelve títulos).
9. **Contar `numOfResults` como providencias** (incluye duplicados .pdf/.doc).
10. **Descargar primero y decidir el alcance después**: borrar ~19.000 autos y reescribir el historial costó trabajo. Decide «¿autos sí o no?» en la entrevista.
11. **Poner el correo del usuario en el User-Agent.** No lo hagas.
12. **Usar `pip3` sin verificar** que corresponde al `python3` que ejecuta el programa.
13. **Hacer consultas lentas al índice** sin la columna inicial del índice único (`corte`).

---

## 12. Adaptar a una fuente nueva (Consejo de Estado, otras salas, tribunales)

**No está verificado** en este proyecto: debes explorarlo. Método que funcionó:

1. **Inspección**: abre la página del buscador. Si el HTML trae los resultados, es raspable con `requests` + BeautifulSoup (como la CC). Si solo trae un `<div id="app">` y un bundle JS, es una SPA: descarga el bundle y busca URLs de backend y textos de consultas (`grep -oE "https?://[^\"']+"`, `grep -o "query.\{0,300\}"`), como se hizo con la CSJ.
2. **Prueba manual de 3 operaciones**: (a) listar por año/tipo, (b) obtener el texto completo de un documento y (c) ver si hay temas o metadatos estructurados. Anota los parámetros exactos que funcionaron.
3. **Mide**: cuántos documentos hay por año, si hay tope de resultados por consulta y cómo paginar.
4. **Revisa `robots.txt`** y si hay cortafuegos (respuestas 403/500 al cambiar el User-Agent o al repetir parámetros).
5. **Escribe un informe corto para el usuario**: «la fuente es viable / parcialmente viable / no viable, porque…», con el volumen y el tiempo estimados. Pide confirmación antes de construir.
6. Si no hay una vía automatizable, alternativas: compilaciones PDF oficiales (gacetas), con el trabajo extra de separar providencias, o un navegador *headless* (Playwright) como último recurso.

**Otras salas de la CSJ**: la misma API sirve (`CIVIL`, `PENAL`, `TUTELAS`, sección 4.2). Ajusta la deducción de sub-sala y radicado a la estructura de rutas de cada sala: Civil trae carpeta de mes; Penal trae el número de proceso entre paréntesis en el nombre del archivo; Tutelas trae la sub-sala después de `TUTELAS/` y carpetas como `Reserva`. **Tutelas es enorme** (28.273 resultados en bruto solo en 2024): pregúntale al usuario si de verdad las necesita y de qué sub-sala.

---

## 13. Volumen y tiempos reales (para estimar)

Sala Laboral de la CSJ, solo sentencias (únicas tras deduplicar, según el año que trae la fuente):

| Año | Sentencias | Año | Sentencias | Año | Sentencias |
|---|---|---|---|---|---|
| 2012 | 1.107 | 2017 | 3.060 | 2022 | 3.901 |
| 2013 | 851 | 2018 | 5.213 | 2023 | 3.113 |
| 2014 | 1.138 | 2019 | 5.126 (+100 con año 2009) | 2024 | 2.904 |
| 2015 | 906 | 2020 | 4.750 | 2025 | 1.390* |
| 2016 | 1.013 | 2021 | 5.029 | 2026 | 43* |

\* Publicación aún incompleta en noviembre de 2026. Nota: la lista del buscador de un año puede incluir providencias que la fuente asigna a otro año (la de 2021 trajo 6.552, de las cuales 1.523 ya venían en la de 2022). Por eso se deduplica por radicado y no por año.

Corte Constitucional 1992–2026: 21.262 tutelas, 7.532 de constitucionalidad y 660 de unificación (~500–1.300 tutelas por año). Los autos (excluidos) sumaban otros ~8.500 solo entre 2022 y 2026.

Espacio: ~45 KB por sentencia de la CSJ y ~90 KB por sentencia de la CC en Markdown + JSON. En GitHub se comprime a ~¼.

Fórmula de estimación: `tiempo ≈ (páginas_de_enumeración + documentos × solicitudes_por_documento) × 1,5 s`.

---

## 14. Plan de construcción por fases (con criterios de aceptación)

| Fase | Entregable | Criterio de aceptación |
|---|---|---|
| 0. Entrevista | Resumen confirmado por el usuario | El usuario dijo «sí, eso» |
| 1. Exploración | Informe de viabilidad de la fuente | Las 3 operaciones (listar, texto, metadatos) funcionan en vivo |
| 2. Conteo | Tabla de volumen por año y tipo + estimación de tiempo y espacio | El usuario aprobó el alcance |
| 3. Esqueleto | Repo con `.gitignore`, `requirements.txt`, módulos vacíos y README | Se instala y `--help` funciona |
| 4. Muestra | 5–20 documentos de punta a punta | El usuario revisó 2–3 `.md` y la clasificación |
| 5. Robustez | `--max-minutos`, enumeración guardada, commit inmediato, `--reconstruir-indice` | Una tanda cortada a propósito retoma sin perder nada |
| 6. Volumen | Tandas + `push` tras cada una | Log sin errores; conteo del índice = archivos en disco = listas de la fuente |
| 7. Verificación | Informe final (totales por año/tema, sin clasificar, faltantes) | 0 faltantes frente a las listas guardadas |
| 8. Documentación | README para el usuario no técnico | Explica dónde están los datos y cómo actualizar |

### 14.1 Verificación final (el script debe calcular esto)

- `COUNT(*)` del índice = número de `*_metadata.json` en disco = filas de la tabla FTS.
- Por cada lista en `estado_enumeracion/`: cuántos radicados no están en el índice (debe ser 0, salvo páginas genéricas o errores explicados).
- Reparto por año, tipo, sub-sala y tema; número de «Otros - Sin clasificar».
- Ningún `.pdf`, `.doc` ni `.sqlite` en git; ningún archivo de más de 100 MB.

---

## 15. Consideraciones jurídicas y éticas

- Las sentencias son **documentos públicos**, pero pueden contener datos personales. Las tutelas sensibles suelen venir anonimizadas por la propia Corte; no intentes revertir esa anonimización. Si el usuario va a publicar el repositorio, recuérdale la Ley 1581 de 2012 (protección de datos personales).
- La clasificación por reglas y cualquier extracción con IA son **orientativas**: ninguna ficha o regla de decisión extraída automáticamente debe citarse en una actuación sin verificación humana del texto original.
- Respeta las condiciones de uso de cada sitio, el ritmo de solicitudes y `robots.txt`. Si un sitio bloquea el acceso automatizado, no intentes evadir el bloqueo: informa al usuario.
- Menciona siempre la fuente oficial y la fecha de descarga (`doc_id_origen`, `fecha_descarga`).

---

## 16. Primer mensaje sugerido al usuario (plantilla)

> «Leí la especificación. Antes de programar necesito entender qué jurisprudencia necesitas. Te voy a hacer unas preguntas cortas; si no sabes alguna respuesta, te propongo una opción. 1) ¿De qué corte (y sala) necesitas sentencias? 2) ¿Solo sentencias o también autos? 3) ¿Desde qué año? 4) ¿Qué temas de tu área te interesan más? …»

Después de la entrevista, sigue el plan de la sección 14 y mantén al usuario informado al final de cada fase.
