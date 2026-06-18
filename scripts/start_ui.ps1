# CareerSignal HH — Local UI Launcher (PowerShell)
# Run: .\scripts\start_ui.ps1

$ErrorActionPreference = "Stop"

# Activate venv if exists
if (Test-Path ".venv\Scripts\Activate.ps1") {
    . .venv\Scripts\Activate.ps1
    Write-Host "Activated .venv"
} elseif (Test-Path ".venv\Scripts\activate") {
    & .venv\Scripts\activate
}

# Create log dir
$logDir = "logs"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

$logFile = Join-Path $logDir ("ui_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".log")
Write-Host "Log: $logFile"

# Start UI
Write-Host "Starting CareerSignal HH Local UI..."
python -m src.main ui --open-browser 2>&1 | Tee-Object -FilePath $logFile
