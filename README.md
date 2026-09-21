# Descargador de Jurisprudencia — Sala Laboral de la Corte Suprema de Justicia

Descarga y organiza providencias (sentencias y autos) de la **Sala de
Casación Laboral** y la **Sala de Descongestión Laboral** de la Corte
Suprema de Justicia de Colombia, clasificándolas por tema, para poder
alimentar luego un agente de IA con jurisprudencia laboral consultable.

## ¿Qué hace?

1. Consulta la API oficial (no documentada públicamente, pero abierta) del
   buscador de providencias de la CSJ, año por año.
2. Para cada providencia nueva: descarga el texto completo, lo convierte a
   Markdown limpio, descarga también el archivo original (PDF o Word) como
   respaldo, y lo clasifica por tema/subtema usando reglas de palabras
   clave (sin usar ninguna IA de pago — ver "Decisiones" más abajo).
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
          SL208-2026.pdf
          SL208-2026_metadata.json
        ...
    sala-descongestion-laboral/
      ...
  indice.sqlite
```

Cada `.md` trae un encabezado con radicado, magistrado ponente, fecha,
tema/subtema y normas citadas, seguido del texto completo. El
`indice.sqlite` tiene una tabla `providencias` (metadatos + rutas) y una
tabla de búsqueda de texto completo `providencias_fts`.

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
```

El programa se corre **manualmente**, cuando tú lo necesites — no queda
programado ni corre en segundo plano.

## Decisiones tomadas en este proyecto

- **Fuente**: la API GraphQL interna de
  `consultaprovidencias.cortesuprema.gov.co` (descubierta explorando el
  código de esa página). No requiere autenticación ni tiene captcha.
- **Sin clasificación por IA**: la Corte Suprema (a diferencia de la Corte
  Constitucional) no publica un tema/subtema oficial como metadato. Por
  decisión del usuario (sin presupuesto para API de pago), la
  clasificación se hace solo con reglas de palabras clave
  (`src/csj_scraper/taxonomy.py`). Las providencias que no calzan en
  ninguna categoría quedan en "Otros - Sin clasificar" para revisión
  manual.
- **Formato de guardado**: Markdown (para que un agente de IA lo indexe
  fácilmente) + PDF/Word original (respaldo) + JSON de metadatos.
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
