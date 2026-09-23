# Especificación de unificación: descargadores de jurisprudencia (CSJ + Corte Constitucional)

**Para:** la conversación/proyecto del descargador de la **Corte Constitucional**.
**De:** el proyecto del descargador de la **Corte Suprema de Justicia — Sala Laboral** (repo `zuniga0123/Descargador-Sentencias-CSJ`).
**Objetivo:** que ambos descargadores funcionen igual (dónde guardan, qué formato producen y cómo se ejecutan) para que el paso siguiente —unificar los datos y montar la app local de búsqueda/gestión de casos— lea un solo formato.

> Instrucción para Claude en la otra conversación: adapta el descargador de la Corte Constitucional a este contrato. Donde este documento dice **DEBE**, es obligatorio para que la unificación funcione. Donde dice **RECOMENDADO**, usa tu criterio con el código existente. No cambies la forma en que se consulta la Relatoría (la fuente sigue siendo la misma); lo que cambia es **dónde y cómo se guarda el resultado**.

---

## 1. Cambio principal: los datos van a GitHub, no al PC

El usuario ejecuta los descargadores desde **Claude Code en la web**. Ese entorno es un contenedor **efímero**: se borra por inactividad o al cerrar la sesión. Por eso:

- Los archivos descargados **NO** se guardan en el PC del usuario ni en rutas locales fuera del repositorio.
- Se guardan **dentro del repositorio**, en la carpeta `jurisprudencia/`, y se hace **`git commit` + `git push` por lotes** apenas termina cada lote.
- Un lote es **un año** (o medio año, separando sentencias y autos, si el año es muy grande; en la CSJ un año puede tener hasta ~16.000 providencias).
- El programa es **resumible**: si se interrumpe, al volver a correrlo salta lo que ya está descargado.
- Se ejecuta **manualmente** cuando el usuario lo pide; no hay tareas programadas.

### Reglas para los commits de datos (DEBE)

1. Solo se suben **texto y metadatos**: `.md` y `_metadata.json`.
2. **No** se suben los originales (PDF, Word, `.htm` descargados) ni el índice SQLite (ver sección 5).
3. **Ningún archivo puede pesar más de 100MB**: GitHub rechaza el `push`. Esto ya nos pasó con el índice SQLite, que llegó a 98MB con solo dos años de datos.
4. Un commit por lote, con un mensaje que diga corte, año y cantidad. Por ejemplo: `Agregar lote de datos: Corte Constitucional 2024 (1.234 providencias)`.

`.gitignore` de referencia (el que usa el proyecto CSJ):

```gitignore
__pycache__/
*.pyc
.venv/
venv/

/jurisprudencia/**/*.pdf
/jurisprudencia/**/*.doc
/jurisprudencia/**/*.docx
/jurisprudencia/**/*.htm
/jurisprudencia/**/*.html
/jurisprudencia/indice.sqlite
/jurisprudencia/indice.sqlite-wal
/jurisprudencia/indice.sqlite-shm
```

---

## 2. Estructura de carpetas (DEBE)

```
jurisprudencia/
  <corte-slug>/
    <nivel-2-slug>/
      <tema-slug>/
        <subtema-slug>/
          <RADICADO>.md
          <RADICADO>_metadata.json
```

| Corte | `<corte-slug>` | `<nivel-2>` |
|---|---|---|
| Corte Suprema de Justicia (Sala Laboral) | `corte-suprema-sala-laboral` | Sub-sala: `sala-casacion-laboral` o `sala-descongestion-laboral` |
| Corte Constitucional | `corte-constitucional` | Área del derecho (las 10 áreas del brief de la Fase 1), p. ej. `derechos-fundamentales-y-debido-proceso` |

- **Slugs:** minúsculas, sin tildes ni eñes, con guiones en lugar de espacios o signos. La función que usa la CSJ es:

  ```python
  import re, unicodedata
  def slugify(texto: str) -> str:
      texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
      texto = re.sub(r"[^a-z0-9]+", "-", texto.lower().strip())
      return texto.strip("-") or "sin-nombre"
  ```

- **Nombre de archivo:** el radicado tal como lo publica la corte, **sin extensión y sin espacios**. CSJ: `SL208-2026`, `AL3319-2025`. Corte Constitucional: `T-388-19`, `C-355-06`, `SU-214-16`.
- **Regla clave:** la app unificada **no deducirá nada de la ruta**. Todo lo que necesita está en el `_metadata.json`. Las carpetas solo sirven para navegar a mano. Por eso el nivel 2 puede ser distinto en cada corte.
- Los casos sin clasificar van a `otros-sin-clasificar/sin-subtema/`.

---

## 3. Archivo `<RADICADO>_metadata.json` (DEBE)

UTF-8, `ensure_ascii=False`, indentado con 2 espacios. Ejemplo real de la CSJ:

```json
{
  "radicado": "SL1121-2024",
  "corte": "Corte Suprema de Justicia",
  "sala": "LABORAL",
  "sub_sala": "DESCONGESTION",
  "tipo_providencia": "SENTENCIA",
  "ano": 2024,
  "fecha_creacion": "2024-05-21T20:20:07Z",
  "magistrado_ponente": "Dra. Cecilia Margarita Duran Ujueta",
  "area": "Derecho Laboral y Seguridad Social",
  "tema": "Prescripción y Caducidad",
  "subtema": "Prescripción de derechos laborales",
  "puntaje_clasificacion": 41,
  "leyes_o_articulos": ["Ley 527 de 1999"],
  "doc_id_origen": "/var/www/html/Index/LABORAL/DESCONGESTION/2024/Dra. Cecilia Margarita Duran Ujueta/Sentencias/SL1121-2024.pdf",
  "fecha_descarga": "2026-09-22T22:46:46.194468+00:00"
}
```

### Campos y cómo llenarlos en la Corte Constitucional

| Campo | Tipo | Oblig. | CSJ | Corte Constitucional |
|---|---|---|---|---|
| `radicado` | texto | Sí | `SL208-2026` | `T-388-19` (igual que el nombre de archivo) |
| `corte` | texto | Sí | `"Corte Suprema de Justicia"` | **Exactamente** `"Corte Constitucional"` |
| `sala` | texto | Sí | `"LABORAL"` | `"PLENA"` o `"REVISION"`, según el campo Sala de la Relatoría |
| `sub_sala` | texto | Sí | `"PERMANENTE"` o `"DESCONGESTION"` | La sala de revisión si la Relatoría la trae (p. ej. `"SEPTIMA DE REVISION"`); si no, igual que `sala`. **Nunca vacío**: forma parte de la clave única |
| `tipo_providencia` | texto | Sí | `"SENTENCIA"` / `"AUTO"` | `"SENTENCIA"` / `"AUTO"` (mayúsculas) |
| `ano` | entero | Sí | 2024 | Año de la providencia |
| `fecha_creacion` | ISO 8601 o null | Sí (puede ser null) | Fecha del **archivo** en el servidor de la CSJ; **no** es la fecha del fallo | Fecha de la sentencia según la Relatoría (`AAAA-MM-DD`) |
| `magistrado_ponente` | texto o null | Sí | `"Dr. Juan Carlos Espeleta Sanchez"` | Tal como lo trae la Relatoría |
| `area` | texto | Sí | Siempre `"Derecho Laboral y Seguridad Social"` | Una de las 10 áreas del brief de la Fase 1. **Importante:** para el área laboral usa exactamente `"Derecho Laboral y Seguridad Social"` (sin "revisado vía tutela") para que la app pueda filtrar ambas cortes juntas |
| `tema` | texto | Sí | Tema por reglas de palabras clave | Tema **oficial** de la Relatoría |
| `subtema` | texto | Sí | Subtema por reglas | Subtema **oficial** de la Relatoría (`"Sin subtema"` si no hay) |
| `puntaje_clasificacion` | entero o null | Sí | Nº de coincidencias de palabras clave | `null` si viene de la Relatoría; un entero si lo calculaste por reglas |
| `leyes_o_articulos` | lista de texto | Sí (puede ser `[]`) | Normas citadas (dadas por la API) | Normas demandadas/citadas, si la Relatoría las trae; si no, `[]` |
| `doc_id_origen` | texto | Sí | Ruta interna del documento en la CSJ | **URL** de la providencia en la Relatoría, p. ej. `https://www.corteconstitucional.gov.co/relatoria/2019/T-388-19.htm` |
| `fecha_descarga` | ISO 8601 UTC | Sí | `datetime.now(timezone.utc).isoformat()` | Igual |
| `fuente_clasificacion` | texto | RECOMENDADO | (si falta, se asume `"reglas"`) | `"relatoria_oficial"` o `"reglas"` |
| `fecha_providencia` | `AAAA-MM-DD` | RECOMENDADO | Pendiente (hay que extraerla del texto) | Fecha real del fallo |

Se pueden agregar campos propios (por ejemplo `resumen` con el RESUMEN de la Relatoría o `normas_demandadas`). La app unificada ignora los campos que no conoce. Lo que **no** se puede hacer es renombrar ni quitar los campos obligatorios.

---

## 4. Archivo `<RADICADO>.md` (DEBE)

Un encabezado fijo, luego una línea separadora `---` rodeada de líneas en blanco, y luego el texto completo de la providencia en Markdown:

```markdown
# SL208-2026

- **Corte:** Corte Suprema de Justicia
- **Sala:** Sala de Casación Laboral
- **Magistrado ponente:** Dr. Juan Carlos Espeleta Sanchez
- **Fecha:** 2026-04-28T12:58:21Z
- **Tipo de providencia:** SENTENCIA
- **Tema:** Pensiones
- **Subtema:** Régimen de transición y RAIS/RPM
- **Normas citadas:** Decreto 758 de 1990, Ley 100 de 1993, Ley 797 de 2003

---

(texto completo de la providencia en Markdown)
```

- El separador **debe** ser exactamente `\n---\n\n` y **debe** ser la primera aparición de esa secuencia en el archivo: el índice separa encabezado y cuerpo con `texto.partition("\n---\n\n")`.
- Las etiquetas del encabezado son las mismas en ambas cortes. En la Corte Constitucional, `Sala` lleva el nombre legible (p. ej. `Sala Plena` o `Sala Séptima de Revisión`).
- **Cuerpo:** convertir el HTML de la Relatoría (`.htm`) a Markdown. La CSJ usa `beautifulsoup4` + `markdownify` (`heading_style="ATX"`), quita las etiquetas de resaltado del buscador (`<mark>`), junta los saltos de línea excesivos y conserva los títulos de sección (ANTECEDENTES, CONSIDERACIONES, RESUELVE) como `##`.
- Si la Relatoría trae TEMA y RESUMEN como texto, se recomienda guardarlos en el JSON (`resumen`) y **no** mezclarlos en el cuerpo, que debe ser solo el texto de la providencia.

---

## 5. Índice SQLite: derivado, local, reconstruible (DEBE)

- `jurisprudencia/indice.sqlite` **no se sube a GitHub**. Con texto completo pesa cientos de MB: en la CSJ son 479MB con solo dos años y medio de datos.
- Se reconstruye desde los `.md` + `_metadata.json` con `python main.py --reconstruir-indice`.
- Si el programa arranca sin índice y ya hay providencias descargadas, lo reconstruye automáticamente antes de descargar. Sin esto, en un contenedor nuevo volvería a bajar todo desde cero.
- La reanudación ("¿ya descargué este radicado?") se consulta en el índice.

Esquema común (el mismo en ambas cortes, para que la app unificada pueda reconstruir un solo índice con las dos):

```sql
CREATE TABLE IF NOT EXISTS providencias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    corte TEXT NOT NULL,
    sala TEXT NOT NULL,
    sub_sala TEXT NOT NULL,
    tipo_providencia TEXT,
    radicado TEXT NOT NULL,
    ano INTEGER,
    fecha_creacion TEXT,
    magistrado_ponente TEXT,
    area TEXT,
    tema TEXT,
    subtema TEXT,
    puntaje_clasificacion INTEGER,
    leyes_o_articulos TEXT,          -- JSON (lista)
    doc_id_origen TEXT NOT NULL,
    ruta_markdown TEXT,              -- relativa a la raíz del repo
    ruta_original TEXT,              -- null: no se guardan originales
    ruta_metadata TEXT,
    fecha_descarga TEXT NOT NULL,
    UNIQUE (corte, radicado, sub_sala)
);
CREATE INDEX IF NOT EXISTS idx_providencias_tema ON providencias (tema, subtema);
CREATE INDEX IF NOT EXISTS idx_providencias_ano ON providencias (ano);
CREATE INDEX IF NOT EXISTS idx_providencias_sub_sala ON providencias (sub_sala);

-- rowid de providencias_fts = providencias.id
CREATE VIRTUAL TABLE IF NOT EXISTS providencias_fts USING fts5(
    radicado, tema, subtema, texto_completo,
    tokenize='unicode61 remove_diacritics 2'
);
```

- Al insertar en `providencias_fts`, **usa `rowid = providencias.id`**. Si no, la búsqueda devuelve coincidencias sin poder decir de qué providencia son. La primera versión de la CSJ tenía justamente ese error.
- `remove_diacritics 2` permite buscar `pension` y encontrar "pensión".
- Consulta de ejemplo:

  ```sql
  SELECT p.corte, p.radicado, p.tema, p.ruta_markdown
  FROM providencias_fts f JOIN providencias p ON p.id = f.rowid
  WHERE providencias_fts MATCH 'estabilidad reforzada'
  ORDER BY rank LIMIT 20;
  ```

---

## 6. Interfaz de línea de comandos (RECOMENDADO, mismo estilo)

```bash
pip install -r requirements.txt
python main.py --anio 2024                    # un año
python main.py --anio 2015-2024               # rango
python main.py --anio 2024 --tipo SENTENCIA   # solo sentencias (partir años grandes)
python main.py --anio 2024 --limite 20        # prueba pequeña
python main.py --reconstruir-indice           # regenerar el índice desde los archivos
```

Scraping respetuoso, igual en ambas: user-agent identificable, ~1,5 s entre solicitudes, reintentos con backoff exponencial (2, 4, 8, 16 s) ante errores de red, 429 o 5xx.

---

## 7. Forma de trabajo en cada sesión (DEBE)

1. Al abrir la sesión: el repositorio ya trae los `.md` y `.json` de lotes anteriores; el índice se reconstruye solo.
2. Lanzar el lote (un año, o una mitad) **en segundo plano**.
3. Al terminar: revisar errores en el log y el porcentaje de "Otros - Sin clasificar"; verificar que no se cuele ningún PDF/HTML ni ningún archivo de más de 100MB (`git status`).
4. `git add jurisprudencia/` → commit → `git push` **antes** de lanzar el siguiente lote.

---

## 8. Lista de cambios para el descargador de la Corte Constitucional

- [ ] Guardar la salida en `jurisprudencia/corte-constitucional/<area>/<tema>/<subtema>/` **dentro del repositorio**, no en el PC del usuario.
- [ ] Dejar de guardar el `.htm` original (o excluirlo en `.gitignore`); guardar el cuerpo convertido a `.md` con el encabezado de la sección 4.
- [ ] Generar `<RADICADO>_metadata.json` con **todos** los campos obligatorios de la sección 3, con `corte = "Corte Constitucional"`.
- [ ] Usar exactamente `"Derecho Laboral y Seguridad Social"` como nombre del área laboral.
- [ ] Adoptar el esquema SQLite de la sección 5, incluido `rowid = providencias.id` en la tabla FTS.
- [ ] Sacar `indice.sqlite` de git y agregar `--reconstruir-indice` + reconstrucción automática si falta.
- [ ] Hacer la descarga resumible consultando el índice.
- [ ] Commit + push por año; nunca un archivo de más de 100MB.
- [ ] Actualizar el README con esta forma de trabajo.

---

## 9. Pendientes para la fase de unificación (fuera de este documento)

- **¿Un repositorio o dos?** Mientras tanto, cada descargador sigue en su propio repositorio con la misma estructura. Como las carpetas de primer nivel no chocan (`corte-suprema-sala-laboral/` y `corte-constitucional/`), luego se pueden juntar en un solo repositorio de datos, o la app puede leer ambos.
- **Fecha real de la providencia en la CSJ:** hoy `fecha_creacion` es la fecha del archivo en el servidor. Falta extraer la fecha del fallo del texto ("Bogotá D. C., once (11) de febrero de dos mil veintiséis").
- **Clasificación de la CSJ:** es por reglas de palabras clave. Cerca del 5% queda sin clasificar, y los casos mixtos se asignan al tema con más coincidencias.
- **App local (localhost:8000):** base centralizada, extracción de hechos, normas y *ratio*, búsqueda semántica y gestión de casos con historial. Leerá únicamente los `.md` y `_metadata.json` descritos aquí.
