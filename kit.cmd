@echo off
rem Lanzador Windows: kit COMANDO ... (no requiere activar ni cambiar la politica de PowerShell)
if not exist "%~dp0.venv-win\Scripts\python.exe" (
    echo Falta el entorno local. Ejecute: py -3 -B scripts\setup.py 1>&2
    exit /b 2
)
"%~dp0.venv-win\Scripts\python.exe" -B "%~dp0kit.py" %*
