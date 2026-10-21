# Descargador de Jurisprudencia — Sala Laboral de la Corte Suprema de Justicia

Descarga y organiza providencias (sentencias y autos) de la **Sala de
Casación Laboral** y la **Sala de Descongestión Laboral** de la Corte
Suprema de Justicia de Colombia, clasificándolas por tema, para poder
alimentar luego un agente de IA con jurisprudencia laboral consultable.

## ¿Qué hace?

1. Consulta la API oficial (no documentada públicamente, pero abierta) del
   buscador de providencias de la CSJ, año por año.
2. Para cada providencia nueva: descarga el texto completo, lo convierte a
   Markdown limpio y lo clasifica por tema/subtema usando reglas de
   palabras clave (sin usar ninguna IA de pago — ver "Decisiones" más
   abajo).
3. Guarda todo organizado en carpetas y registra cada providencia en un
   índice SQLite consultable (`jurisprudencia/indice.sqlite`).

## Estructura de resultado

```
jurisprudencia/
  corte-suprema-sala-laboral/
    sala-casacion-laboral/
      pensiones/
        pension-de-vejez/
          SL208-2026.md
          SL208-2026_metadata.json
        ...
    sala-descongestion-laboral/
      ...
  indice.sqlite        # local, no se sube a GitHub (ver abajo)
```

Cada `.md` trae un encabezado con radicado, magistrado ponente, fecha,
tema/subtema y normas citadas, seguido del texto completo.

Los `.md` y `_metadata.json` son la **fuente de verdad** y se suben a
GitHub. El `indice.sqlite` es un derivado local (tabla `providencias` con
metadatos + rutas, y tabla de búsqueda de texto completo
`providencias_fts`, cuyo `rowid` es el `id` de `providencias`). No se sube
a GitHub porque pesa cientos de MB; después de clonar el repositorio se
regenera con:

```bash
python main.py --reconstruir-indice
```

El formato común con el proyecto de la Corte Constitucional está en
[`docs/ESPECIFICACION_UNIFICACION.md`](docs/ESPECIFICACION_UNIFICACION.md).

## Instalación

Requiere Python 3.10 o superior.

```bash
pip install -r requirements.txt
```

## Uso

```bash
# Prueba pequeña: máximo 20 providencias nuevas del año actual
python main.py --anio 2026 --limite 20

# Un año completo
python main.py --anio 2024

# Un rango de años
python main.py --anio 2015-2024

# Todo el rango por defecto (últimos 15 años) — puede tardar horas/días,
# se puede interrumpir (Ctrl+C) y volver a correr después: no vuelve a
# descargar lo que ya esté en el índice.
python main.py

# Por tandas de 25 minutos (entornos que cortan procesos largos): se
# detiene sola, guarda el avance y el mismo comando continúa donde quedó.
python main.py --anio 2022 --tipo SENTENCIA --max-minutos 25
```

El programa se corre **manualmente**, cuando tú lo necesites — no queda
programado ni corre en segundo plano.

### Reanudación

- Cada providencia descargada queda registrada en el índice en el momento,
  así que una corrida cortada a la mitad no pierde lo ya bajado.
- La lista de providencias de cada año/tipo (que puede tardar más de 30
  minutos en recorrerse) se guarda en `estado_enumeracion/` y se sube a
  GitHub: una enumeración interrumpida continúa donde quedó, y una
  completa no se repite. Para años recientes en los que la Corte sigue
  publicando, `--reenumerar` vuelve a consultar la lista.
- Al final de cada corrida el log dice `ESTADO: COMPLETO` o
  `ESTADO: INCOMPLETO` (en ese caso, volver a correr el mismo comando).

## Corte Constitucional

El mismo programa descarga también las providencias de la **Corte
Constitucional** (todas las áreas, desde 1992: tutelas, constitucionalidad y
unificación; los autos no se descargan salvo que se pidan con `--tipo A`),
con el mismo formato (`.md` + `_metadata.json`, ver
[`docs/ESPECIFICACION_UNIFICACION.md`](docs/ESPECIFICACION_UNIFICACION.md)).

- **Dónde se guardan:** en el repositorio aparte
  [`Descargador-Sentencias-CC`](https://github.com/zuniga0123/Descargador-Sentencias-CC),
  rama `datos`, que debe estar clonado junto a este
  (`../descargador-sentencias-cc`; otra ruta con la variable de entorno
  `CC_DATOS_DIR`). Cada lote se sube a GitHub desde esa carpeta.
- **Fuente:** el buscador de la Relatoría
  (`corteconstitucional.gov.co/relatoria/buscador_new/`). Se enumera por
  tipo y año (una consulta trae hasta 5.000 resultados); por cada
  providencia se baja el texto (`.htm`) y sus **temas/subtemas oficiales**
  ("titulaciones" de la Relatoría). El área del derecho se asigna con reglas
  sobre esos temas (`src/cc_scraper/areas.py`).
- **Estructura:** `jurisprudencia/corte-constitucional/<área>/<tema>/<subtema>/`
  (nombres de carpeta recortados a 60 caracteres para que funcione en
  Windows).
- Los números que faltan en la numeración (p. ej. T-017/19) no están
  publicados: el sitio responde con una página genérica vacía.

```bash
python main.py --corte constitucional --anio 2019 --tipo T --limite 5   # prueba
python main.py --corte constitucional --anio 1992-2026 --max-minutos 25 # por tandas
python main.py --corte constitucional --reconstruir-indice
```

## Decisiones tomadas en este proyecto

- **Fuente**: la API GraphQL interna de
  `consultaprovidencias.cortesuprema.gov.co` (descubierta explorando el
  código de esa página). No requiere autenticación ni tiene captcha.
- **Sin clasificación por IA**: la Corte Suprema (a diferencia de la Corte
  Constitucional) no publica un tema/subtema oficial como metadato. Por
  decisión del usuario (sin presupuesto para API de pago), la
  clasificación se hace solo con reglas de palabras clave
  (`src/csj_scraper/taxonomy.py`). Si ningún tema de fondo coincide, se
  prueba con "Trámite procesal" (deserción del recurso, desistimiento,
  conflictos de competencia, nulidades, costas, etc.), pensado para los
  autos de trámite. Lo que tampoco calza queda en "Otros - Sin
  clasificar"; dentro de eso, "Texto incompleto en la fuente" agrupa los
  documentos de los que la Corte solo publica la constancia de
  notificación/ejecutoria, sin el texto de la providencia (no se puede
  recuperar por esta vía).
- **Ajustar las reglas**: después de editar `taxonomy.py`,
  `python main.py --reclasificar` vuelve a clasificar todo lo descargado
  sin consultar la fuente (mueve los archivos y actualiza JSON, Markdown
  e índice).
- **Formato de guardado**: Markdown (para que un agente de IA lo indexe
  fácilmente) + JSON de metadatos. El PDF/Word original solo se descarga
  con `--con-original` (duplica tiempo y espacio; ~89,000 providencias en
  15 años no caben con PDF en el entorno de trabajo).
- **Persistencia**: el entorno donde corre el descargador es efímero, así
  que cada lote (un año, o medio año si es grande) se sube a GitHub apenas
  termina.
- **Enumeración**: la API no ofrece un modo "traer todo"; hay que buscar
  con un texto. Se usa la palabra "de" (aparece en prácticamente cualquier
  providencia en español) para enumerar, paginando de a 10 resultados.
- **Scraping respetuoso**: pausa de ~1.5s entre solicitudes y reintentos
  con backoff exponencial ante errores.

## Siguiente paso (fuera del alcance de este programa)

El objetivo final es alimentar un agente de IA que sirva como ecosistema
de trabajo judicial (base de datos centralizada, extracción de hechos
relevantes/normas/ratio decidendi por sentencia, búsqueda semántica, app
local). Ese desarrollo es una fase posterior; este descargador solo deja
los datos limpios y organizados, listos para esa siguiente etapa.
