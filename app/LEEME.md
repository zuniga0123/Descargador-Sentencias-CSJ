# Buscador de Jurisprudencia (app local)

Busca en las sentencias de la **Corte Suprema de Justicia – Sala Laboral**
(Sala de Casación Laboral y Sala de Descongestión Laboral, 2012 en adelante)
y de la **Corte Constitucional** (1992 en adelante) desde el navegador, sin
internet y sin pagar ninguna API. Todo corre en tu computador.

## Instalar en Windows (una sola vez)

1. Descarga el instalador (un ZIP pequeño):
   <https://raw.githubusercontent.com/zuniga0123/Descargador-Sentencias-CSJ/claude/csj-colombia-sentencias-app-7eisz7/app/windows/instalador_buscador.zip>
2. Abre la carpeta Descargas, clic derecho sobre `instalador_buscador.zip` →
   **Extraer todo** → **Extraer**. En la carpeta que se abre, doble clic en
   `instalar_buscador.bat`. Si Windows muestra "Windows protegió su PC", pulsa
   **Más información → Ejecutar de todas formas**.

   (No guardes el `.bat` desde el navegador con Ctrl + S: el navegador lo guarda
   como `.txt` y al abrirlo solo aparece el Bloc de notas.)
3. Espera: instala Python si hace falta, baja las sentencias (≈1,4 GB) y arma la
   base de búsqueda. La primera vez tarda entre 15 y 30 minutos.
4. Al terminar queda un acceso directo **Buscador de Jurisprudencia** en el
   escritorio. Todo se guarda en `C:\Users\<tu usuario>\BuscadorJurisprudencia`.

Requisitos: Windows 10 u 11 y unos 5 GB libres durante la instalación
(después ocupa unos 3 GB: los ZIP descargados se borran al terminar).

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

## Casos y búsqueda de precedentes

En **Mis casos** cada persona crea sus casos (al entrar elige su nombre; no
hay contraseña, sirve para separar el trabajo).

1. **Nuevo caso** → escribe los hechos y particularidades como se los
   contarías a un colega, lo que se pide o se discute, y **a qué parte
   representas** (trabajadora, empleadora o análisis neutral). Puedes limitar
   cortes y años, y dar prioridad a las sentencias recientes (activado por
   defecto). Todo se guarda solo.
2. **Buscar precedentes**. Con DeepSeek el resultado tiene dos partes:
   - **Temas jurídicos a resolver**: las cuestiones que el caso debe decidir
     (incluidas las previas, como prescripción o legitimación). En cada una:
     qué dice la jurisprudencia encontrada, **argumentos** para tu parte con
     su apoyo, la objeción previsible, lo que alegará la contraparte, lo que
     hay que verificar en el expediente y los vacíos. Una revisión crítica
     marca los argumentos que podrían perjudicar a tu propia parte.
   - **Sentencias evaluadas**: de cada una, el resultado (qué decidió y a quién
     favoreció), si decidió el fondo, sus reglas marcadas como *ratio*,
     *reiteración* u *obiter* con la **cita textual**, y la comparación hecho
     por hecho con el caso.
3. **☆ Guardar en el caso** las que sirven (con tus notas) y **No sirve** las
   que no: estas ya no vuelven a aparecer en las búsquedas de ese caso.
4. **Exportar informe**: un archivo .md con los hechos, los temas jurídicos,
   los argumentos y los precedentes elegidos con su cita, listo para Word.
5. El **Historial** registra quién hizo qué y cuándo. Desde el buscador general
   también se puede guardar una sentencia en un caso (botón en el lector).

### Cómo evita la app que la IA "acomode" las sentencias

- La IA lee cada sentencia **sin conocer el caso** y hace una ficha neutra
  (hechos, resultado, reglas). Solo después la compara con el caso, y en esa
  comparación no puede cambiar lo que dice la ficha.
- Cada regla y cada resultado traen una **cita literal** que la app busca en el
  texto completo de la sentencia: ✓ si la encontró (con enlace "ver en el
  texto"), ⚠ si no la encontró (no la uses sin revisar).
- La similitud de hechos la calcula la app a partir de la comparación hecho por
  hecho, no la IA a ojo.
- Si la IA cita una sentencia que no está entre las revisadas para ese tema, la
  app la marca como no verificada.
- Las cortes tienen cupos separados: las tutelas de la Corte Constitucional no
  desplazan a la Sala Laboral.

### Con DeepSeek (recomendado) o sin IA

- **Sin IA** funciona por palabras clave del caso: útil, pero sin explicaciones.
- **Con DeepSeek** la primera búsqueda de un caso tarda entre 1 y 4 minutos:
  la IA lee unas 40 sentencias (u 80) y usa alrededor de 180.000 tokens. Las
  fichas de las sentencias quedan guardadas en `datos/cache_ia.sqlite`, así que
  las búsquedas siguientes que vuelven a encontrar esas sentencias son mucho
  más rápidas y baratas (unos 20.000 tokens). El costo depende de las tarifas
  vigentes de DeepSeek; es prepago.
- Para activarlo: **Configuración** → pega la clave de API de DeepSeek
  (platform.deepseek.com → API keys) → **Guardar**. Se prueba sola. La clave
  se guarda únicamente en ese computador; quienes usan el buscador en red
  aprovechan la misma clave, pero no pueden verla ni cambiarla.
- **Privacidad**: a DeepSeek se envían los hechos y pretensiones del caso y
  extractos de sentencias públicas, nunca la base completa. No escribas en los
  casos nombres, cédulas ni datos que identifiquen a las personas.
- Las calificaciones y la síntesis son orientativas: verifica cada sentencia
  antes de citarla.

Los casos se guardan en `datos/casos.sqlite`, aparte de las sentencias:
actualizar el buscador no los borra. Para respaldarlos, copia ese archivo.

## Para quien programa

```
app/
  config.py         rutas, fuentes (ZIP de GitHub) y puerto
  preparar_datos.py lee los ZIP sin descomprimir -> datos/jurisprudencia.sqlite
  busqueda.py       motor: FTS5 + filtros + facetas + fragmentos
  servidor.py       API (FastAPI) y páginas; documentación en /api/docs
  ia.py             conexión opcional con DeepSeek (formato OpenAI)
  precedentes.py    buscador de precedentes: planteamiento, candidatas,
                    extractos, evaluación y síntesis (o modo sin IA)
  casos.py          usuarios, casos, análisis, guardadas e historial
  fichas.py         fichas neutras de sentencias con citas verificadas (caché)
  informes.py       informe del caso en Markdown
  texto.py          limpieza del texto (PDF de la Corte Suprema, secciones)
  instalar.py       pasos de instalación con Python
  web/              interfaz (HTML + CSS + JS, sin dependencias; casos.js, analisis.js)
  windows/          instalador y lanzadores .bat
```

En Mac/Linux: `python3 -m venv .venv && .venv/bin/pip install -r app/requirements.txt`,
luego `.venv/bin/python -m app.preparar_datos --descargar` y
`.venv/bin/python -m app.servidor`.

Base de datos (`datos/jurisprudencia.sqlite`): tabla `providencias`
(metadatos), `textos` (Markdown comprimido con zlib) y `fts` (índice FTS5 sin
copia del contenido, `rowid = providencias.id`, sin distinguir tildes).
