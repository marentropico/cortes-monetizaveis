@echo off
cd /d "%~dp0"
echo ===================================================
echo   Hard Cleeps Studio 9:16  ^|  Standalone App
echo ===================================================
if not exist ".venv\Scripts\python.exe" (
    echo [ERRO] Ambiente virtual .venv nao encontrado.
    pause
    exit /b 1
)
set PYTHONUTF8=1
echo Iniciando janela standalone (FastAPI + React Studio)...
".venv\Scripts\python.exe" launcher.py
if errorlevel 1 pause
