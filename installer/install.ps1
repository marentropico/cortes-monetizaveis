param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "HardCleepsStudio"),
    [string]$RepoUrl = "https://github.com/marentropico/Cortes-Monetizaveis.git",
    [string]$Branch = "main"
)

$ErrorActionPreference = "Stop"

function Refresh-Path {
    $m = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $u = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$m;$u"
}

function Ensure-WingetPackage([string]$CmdName, [string]$WingetId, [string]$Label) {
    if (Get-Command $CmdName -ErrorAction SilentlyContinue) {
        Write-Host "[OK] $Label já instalado." -ForegroundColor Green
        return
    }
    Write-Host "[Instalando] $Label ($WingetId)..." -ForegroundColor Yellow
    winget install --id $WingetId --exact --silent --accept-package-agreements --accept-source-agreements
    Refresh-Path
}

Write-Host "=== Hard Cleeps Studio — Instalador ===" -ForegroundColor Cyan

Ensure-WingetPackage "git" "Git.Git" "Git"
Ensure-WingetPackage "python" "Python.Python.3.12" "Python 3.12"
Ensure-WingetPackage "node" "OpenJS.NodeJS.LTS" "Node.js LTS"
Ensure-WingetPackage "ffmpeg" "Gyan.FFmpeg" "FFmpeg"
Ensure-WingetPackage "yt-dlp" "yt-dlp.yt-dlp" "yt-dlp"

if (-not (Test-Path (Join-Path $InstallDir ".git"))) {
    Write-Host "[Git] Clonando repositório em $InstallDir..." -ForegroundColor Cyan
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    git clone --branch $Branch $RepoUrl $InstallDir
} else {
    Write-Host "[Git] Repositório já existe em $InstallDir; atualizando..." -ForegroundColor Cyan
    Push-Location $InstallDir
    git pull --ff-only origin $Branch
    Pop-Location
}

Set-Location $InstallDir

$VenvPy = Join-Path $InstallDir ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
    Write-Host "[Python] Criando ambiente virtual .venv..." -ForegroundColor Cyan
    python -m venv .venv
}

Write-Host "[Python] Instalando dependências..." -ForegroundColor Cyan
& $VenvPy -m pip install --upgrade pip
& $VenvPy -m pip install -r requirements.txt
& $VenvPy -m playwright install chromium

Write-Host "[Frontend] Instalando pacotes e gerando build..." -ForegroundColor Cyan
npm --prefix frontend install
npm run build

if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
    Copy-Item ".env.example" ".env"
}

Write-Host "=== Instalação concluída com sucesso! ===" -ForegroundColor Green
