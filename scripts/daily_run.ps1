# CareerSignal HH Daily Run (Windows Task Scheduler)
# Run manually: powershell -ExecutionPolicy Bypass -File scripts\daily_run.ps1

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectDir

$LogDir = "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = "$LogDir\daily_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"

function Write-Log { param($msg); $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"; "$ts $msg" | Tee-Object -FilePath $LogFile -Append }

Write-Log "=== CareerSignal HH Daily Run ==="
Write-Log "Project: $ProjectDir"

# Activate venv
$VenvActivate = ".venv\Scripts\Activate.ps1"
if (Test-Path $VenvActivate) {
    . $VenvActivate
    Write-Log "Venv activated"
} else {
    Write-Log "WARNING: .venv not found, using system Python"
}

# Autopilot
Write-Log "Running autopilot daily..."
python -m src.main autopilot daily --backup-first --yes 2>&1 | Tee-Object -FilePath $LogFile -Append
$AutoExit = $LASTEXITCODE
Write-Log "Autopilot exit code: $AutoExit"

# Cockpit
Write-Log "Generating cockpit..."
python -m src.main cockpit export 2>&1 | Tee-Object -FilePath $LogFile -Append
Write-Log "Cockpit exit code: $LASTEXITCODE"

# Maintenance report (dry-run only, no deletion)
Write-Log "Running maintenance report..."
python -m src.main maintenance report 2>&1 | Tee-Object -FilePath $LogFile -Append
Write-Log "Maintenance exit code: $LASTEXITCODE"

Write-Log "=== Daily run complete ==="
exit $AutoExit
