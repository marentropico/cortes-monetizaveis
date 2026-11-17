param(
    [Parameter(Mandatory = $true)][string]$RepoDir,
    [string]$Branch = "main",
    [int]$WaitPid = 0
)

$ErrorActionPreference = "Stop"
Set-Location $RepoDir

$LogFile = Join-Path $RepoDir "temp\updater.log"
New-Item -ItemType Directory -Force -Path (Split-Path $LogFile) | Out-Null

function Write-Log([string]$Msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "[$ts] $Msg" | Out-File -FilePath $LogFile -Append -Encoding utf8
}

Write-Log "Aguardando encerramento do backend (PID $WaitPid)..."
if ($WaitPid -gt 0) {
    for ($i = 0; $i -lt 30; $i++) {
        if (-not (Get-Process -Id $WaitPid -ErrorAction SilentlyContinue)) { break }
        Start-Sleep -Milliseconds 300
    }
}

try {
    $Changed = git diff --name-only "HEAD..origin/$Branch" 2>$null
    Write-Log "Executando git pull --ff-only origin $Branch..."
    git pull --ff-only origin $Branch 2>&1 | Out-File -FilePath $LogFile -Append -Encoding utf8

    if ($Changed -match "requirements\.txt") {
        $PipExe = Join-Path $RepoDir ".venv\Scripts\pip.exe"
        if (Test-Path $PipExe) {
            Write-Log "Atualizando dependências Python..."
            & $PipExe install -r (Join-Path $RepoDir "requirements.txt") 2>&1 | Out-File -FilePath $LogFile -Append -Encoding utf8
        }
    }

    if ($Changed -match "^frontend/") {
        $FrontDir = Join-Path $RepoDir "frontend"
        if ($Changed -match "frontend/package\.json") {
            Write-Log "Atualizando pacotes npm do frontend..."
            npm --prefix $FrontDir install 2>&1 | Out-File -FilePath $LogFile -Append -Encoding utf8
        }
        Write-Log "Recompilando frontend..."
        npm --prefix $FrontDir run build 2>&1 | Out-File -FilePath $LogFile -Append -Encoding utf8
    }

    Write-Log "Relançando Hard Cleeps Studio..."
    $PyExe = Join-Path $RepoDir ".venv\Scripts\python.exe"
    if (-not (Test-Path $PyExe)) { $PyExe = "python" }
    Start-Process -FilePath $PyExe -ArgumentList (Join-Path $RepoDir "launcher.py") -WorkingDirectory $RepoDir
    Write-Log "Atualização concluída com sucesso."
} catch {
    Write-Log "ERRO na atualização: $_"
}
