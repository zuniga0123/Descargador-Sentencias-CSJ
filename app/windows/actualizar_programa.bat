@echo off
chcp 65001 >nul
title Actualizar el programa del Buscador de Jurisprudencia
rem Baja solo el programa (unos segundos); no toca la base de sentencias.
rem Para traer sentencias nuevas use actualizar.bat.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" cd /d "%USERPROFILE%\BuscadorJurisprudencia" 2>nul
if not exist ".venv\Scripts\python.exe" (
  echo No se encontro el buscador instalado en %USERPROFILE%\BuscadorJurisprudencia.
  echo Copie este archivo a la carpeta del buscador y vuelva a ejecutarlo.
  pause
  exit /b 1
)
echo.
echo  Cierre la ventana del buscador si esta abierta.
echo.
rem Primero la ultima version del actualizador mismo (asi funciona aunque la instalacion sea antigua).
curl.exe -L --fail -s -o "app\actualizar_programa.nuevo" "https://raw.githubusercontent.com/zuniga0123/Descargador-Sentencias-CSJ/claude/csj-colombia-sentencias-app-7eisz7/app/actualizar_programa.py" && move /y "app\actualizar_programa.nuevo" "app\actualizar_programa.py" >nul
rem Todo en un bloque: la actualizacion puede reemplazar este mismo .bat y cmd ya lo tiene leido.
if not exist "app\actualizar_programa.py" (
  echo No se pudo descargar el actualizador. Revise la conexion a internet o use actualizar.bat
  pause
  exit /b 1
)
(
  ".venv\Scripts\python.exe" -m app.actualizar_programa
  echo.
  pause
  exit /b
)
