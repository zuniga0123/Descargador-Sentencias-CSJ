@echo off
rem Permite que otras personas de la misma red (oficina, casa) usen este buscador
rem desde su navegador. Windows puede pedir permiso en el Firewall: acepta "Redes privadas".
cd /d "%~dp0"
call "%~dp0iniciar.bat" --red
