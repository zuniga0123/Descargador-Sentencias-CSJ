# Buscador de Jurisprudencia (app local)

Busca en las sentencias de la **Corte Suprema de Justicia – Sala Laboral**
(Sala de Casación Laboral y Sala de Descongestión Laboral, 2012 en adelante)
y de la **Corte Constitucional** (1992 en adelante) desde el navegador, sin
internet y sin pagar ninguna API. Todo corre en tu computador.

## Instalar en Windows (una sola vez)

1. Descarga el instalador: abre
   <https://raw.githubusercontent.com/zuniga0123/Descargador-Sentencias-CSJ/claude/csj-colombia-sentencias-app-7eisz7/app/windows/instalar_buscador.bat>
   y guárdalo con **Ctrl + S** (por ejemplo en Descargas).
2. Haz doble clic en `instalar_buscador.bat`. Si Windows muestra
   "Windows protegió su PC", pulsa **Más información → Ejecutar de todas formas**.
3. Espera: instala Python si hace falta, baja las sentencias (≈1,4 GB) y arma la
   base de búsqueda. La primera vez tarda entre 15 y 30 minutos.
4. Al terminar queda un acceso directo **Buscador de Jurisprudencia** en el
   escritorio. Todo se guarda en `C:\Users\<tu usuario>\BuscadorJurisprudencia`.

Requisitos: Windows 10 u 11, unos 4 GB libres durante la instalación
(después ocupa menos: los ZIP descargados se borran).

## Usar

- Doble clic en el acceso directo (o en `iniciar.bat`). Se abre el navegador en
  <http://localhost:8000>. Para cerrar el buscador, cierra la ventana negra.
- **Cómo buscar**
  - palabras sueltas: deben aparecer todas → `pensión sobrevivientes compañera`
  - `"frase exacta"` entre comillas
  - `-palabra` para excluir, `O` para alternativas → `fuero O estabilidad`
  - `pensiona*` para buscar por prefijo; las tildes no importan
  - un radicado (`T-760/08`, `SU-214/16`, `SL1234-2020`) para ir directo
- Filtros a la izquierda: años (o clic en una barra del histograma), corte,
  sala, tipo de sentencia, tema y magistrado ponente.
- Al abrir una sentencia: índice de secciones, términos resaltados, búsqueda
  dentro del texto (Ctrl + F), **Copiar cita** y **Descargar .md** (útil para
  pasarle la sentencia completa a una IA).

## Que otras personas lo usen

- **Cada quien en su computador**: cada persona ejecuta el instalador.
- **Compartido en la misma red** (oficina, casa): en el computador que tiene
  el buscador abre `iniciar_en_red.bat`. La ventana muestra una dirección como
  `http://192.168.1.20:8000`; las demás personas la abren en su navegador.
  Windows puede pedir permiso del Firewall: acepta solo **Redes privadas**.
  Ese computador debe quedar encendido con la ventana abierta.

## Actualizar (sentencias nuevas o nueva versión)

Cierra el buscador y ejecuta `actualizar.bat` en la carpeta del buscador.
Vuelve a bajar los datos de GitHub y reconstruye la base (10–20 minutos).

## IA (opcional, más adelante)

El buscador no necesita IA. Está preparado para conectar **DeepSeek** cuando se
quiera (`app/ia.py`): la búsqueda local escoge las sentencias pertinentes y solo
se envían fragmentos de ellas al modelo, que responde citando radicados. Para
activarlo bastará con guardar la clave de DeepSeek en la variable de entorno
`DEEPSEEK_API_KEY` y reiniciar el buscador; la interfaz para preguntarle a la IA
es la siguiente fase.

## Para quien programa

```
app/
  config.py         rutas, fuentes (ZIP de GitHub) y puerto
  preparar_datos.py lee los ZIP sin descomprimir -> datos/jurisprudencia.sqlite
  busqueda.py       motor: FTS5 + filtros + facetas + fragmentos
  servidor.py       API (FastAPI) y páginas; documentación en /api/docs
  ia.py             conexión opcional con DeepSeek (formato OpenAI)
  instalar.py       pasos de instalación con Python
  web/              interfaz (HTML + CSS + JS, sin dependencias)
  windows/          instalador y lanzadores .bat
```

En Mac/Linux: `python3 -m venv .venv && .venv/bin/pip install -r app/requirements.txt`,
luego `.venv/bin/python -m app.preparar_datos --descargar` y
`.venv/bin/python -m app.servidor`.

Base de datos (`datos/jurisprudencia.sqlite`): tabla `providencias`
(metadatos), `textos` (Markdown comprimido con zlib) y `fts` (índice FTS5 sin
copia del contenido, `rowid = providencias.id`, sin distinguir tildes).
