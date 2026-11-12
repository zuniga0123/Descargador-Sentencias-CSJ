@echo off
setlocal
chcp 65001 >nul
title Instalador del Buscador de Jurisprudencia

rem Carpeta de instalacion: corta a proposito (Windows limita el largo de las rutas).
set "DESTINO=%USERPROFILE%\BuscadorJurisprudencia"
if not "%~1"=="" set "DESTINO=%~f1"
set "ZIP_CODIGO=https://codeload.github.com/zuniga0123/Descargador-Sentencias-CSJ/zip/refs/heads/claude/csj-colombia-sentencias-app-7eisz7"

echo.
echo  ==========================================================
echo    Buscador de Jurisprudencia - instalacion / actualizacion
echo  ==========================================================
echo.
echo  Se instalara en: %DESTINO%
echo  Necesita unos 4 GB libres durante la instalacion y conexion a internet.
echo  La primera vez tarda entre 15 y 30 minutos.
echo.
pause

rem ---------- 1. Python ----------
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "PY=py -3"
if not defined PY python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "PY=python"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY (
  echo  [1/4] No se encontro Python 3.10 o superior. Instalando Python 3.12...
  winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
)
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY (
  echo.
  echo  No fue posible instalar Python automaticamente.
  echo  Instalalo desde https://www.python.org/downloads/ marcando "Add python.exe to PATH"
  echo  y vuelve a ejecutar este instalador.
  pause
  exit /b 1
)
echo  [1/4] Python listo.

rem ---------- 2. Codigo del buscador + sentencias de la Corte Suprema ----------
if not exist "%DESTINO%\descargas" mkdir "%DESTINO%\descargas"
echo  [2/4] Descargando el buscador y las sentencias de la Corte Suprema (unos 600 MB)...
curl.exe -L --fail --retry 3 --progress-bar -o "%DESTINO%\descargas\csj.zip" "%ZIP_CODIGO%"
if errorlevel 1 (
  echo  Fallo la descarga. Revisa la conexion a internet y vuelve a intentarlo.
  pause
  exit /b 1
)
rem Extrae solo la carpeta app\ (el resto del ZIP son los datos, que se leen sin descomprimir).
%PY% -c "import zipfile,sys,pathlib;z=zipfile.ZipFile(sys.argv[1]);d=pathlib.Path(sys.argv[2]);[((d/n.split('/',1)[1]).parent.mkdir(parents=True,exist_ok=True),(d/n.split('/',1)[1]).write_bytes(z.read(n))) for n in z.namelist() if n.split('/',1)[-1].startswith('app/') and not n.endswith('/')]" "%DESTINO%\descargas\csj.zip" "%DESTINO%"
if errorlevel 1 (
  echo  No se pudo extraer el programa del ZIP descargado.
  pause
  exit /b 1
)

rem ---------- 3. Entorno de Python con las librerias del buscador ----------
cd /d "%DESTINO%"
if not exist ".venv\Scripts\python.exe" (
  echo  [3/4] Creando el entorno de Python...
  %PY% -m venv .venv
)
echo  [3/4] Instalando librerias...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r app\requirements.txt
if errorlevel 1 (
  echo  No se pudieron instalar las librerias.
  pause
  exit /b 1
)

rem ---------- 4. Base de busqueda ----------
rem Todo en un bloque: este paso puede actualizar los .bat y cmd ya lo tiene leido.
(
  echo  [4/4] Preparando la base de busqueda...
  ".venv\Scripts\python.exe" -m app.instalar
  echo.
  pause
  exit /b
)
