@echo off
rem Trae las sentencias nuevas y la ultima version del buscador.
rem Cierra primero la ventana del buscador si esta abierta.
rem Se ejecuta una copia temporal del instalador porque la actualizacion
rem reemplaza los archivos del programa (incluido el instalador).
cd /d "%~dp0"
copy /y "%~dp0app\windows\instalar_buscador.bat" "%TEMP%\instalar_buscador_jurisprudencia.bat" >nul
(
  call "%TEMP%\instalar_buscador_jurisprudencia.bat" "%~dp0."
  exit /b
)
