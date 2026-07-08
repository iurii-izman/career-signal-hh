# CareerSignal HH — Local UI Launcher (PowerShell)
# Run: .\scripts\start_ui.ps1

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptRoot "..")).Path

function Resolve-CareerSignalPython {
    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        return $venvPython
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return $python.Source
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return "$($py.Source) -3"
    }

    throw "Python 3.11+ not found. Create .venv or add python to PATH."
}

$pythonCommand = Resolve-CareerSignalPython

# Create log dir
$logDir = Join-Path $repoRoot "logs"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

$logFile = Join-Path $logDir ("ui_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".log")
Write-Host "Log: $logFile"
Write-Host "Repo: $repoRoot"

# Start UI
Write-Host "Starting CareerSignal HH Local UI..."
Push-Location $repoRoot
try {
    if ($pythonCommand -like "* -3") {
        & py -3 -m src.main ui --open-browser 2>&1 | Tee-Object -FilePath $logFile
    } else {
        & $pythonCommand -m src.main ui --open-browser 2>&1 | Tee-Object -FilePath $logFile
    }
} finally {
    Pop-Location
}
