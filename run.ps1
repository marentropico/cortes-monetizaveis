Set-Location $PSScriptRoot
Write-Host "===================================================" -ForegroundColor Cyan
Write-Host "  Hard Cleeps Studio 9:16  |  Standalone App" -ForegroundColor Cyan
Write-Host "===================================================" -ForegroundColor Cyan

$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Error "Ambiente virtual .venv não encontrado."
    exit 1
}

$env:PYTHONUTF8 = "1"
Write-Host "Iniciando janela standalone (FastAPI + React Studio)..." -ForegroundColor Green
& $py launcher.py
