@echo off
chcp 65001 >nul
title Buscador de Jurisprudencia
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Falta instalar el buscador: ejecuta instalar_buscador.bat
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m app.servidor %*
pause
