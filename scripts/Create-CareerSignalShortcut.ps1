# CareerSignal HH — Create Desktop Shortcut
# Run: .\scripts\Create-CareerSignalShortcut.ps1

$ErrorActionPreference = "Stop"

$scriptPath = Join-Path $PSScriptRoot "start_ui.ps1"
$desktopPath = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktopPath "CareerSignal HH.lnk"

if (-not (Test-Path $scriptPath)) {
    Write-Host "ERROR: start_ui.ps1 not found at $scriptPath" -ForegroundColor Red
    exit 1
}

Write-Host "Creating desktop shortcut..." -ForegroundColor Cyan
Write-Host "  Target: $scriptPath" -ForegroundColor Gray
Write-Host "  Shortcut: $shortcutPath" -ForegroundColor Gray

$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($shortcutPath)
$Shortcut.TargetPath = "powershell.exe"
$Shortcut.Arguments = "-ExecutionPolicy Bypass -File `"$scriptPath`""
$Shortcut.WorkingDirectory = (Resolve-Path $PSScriptRoot\..).Path
$Shortcut.WindowStyle = 7  # Minimized
$Shortcut.Description = "CareerSignal HH — Local UI"
$Shortcut.Save()

Write-Host "Shortcut created on Desktop: CareerSignal HH.lnk" -ForegroundColor Green
Write-Host "Double-click to start the UI." -ForegroundColor Green
Write-Host ""
Write-Host "Chrome App Mode (no address bar):" -ForegroundColor Gray
Write-Host "  Start UI first, then: start chrome --app=http://127.0.0.1:8765" -ForegroundColor Gray
