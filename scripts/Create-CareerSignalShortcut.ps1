# CareerSignal HH — Create Desktop Shortcut
# Run: .\scripts\Create-CareerSignalShortcut.ps1

$ErrorActionPreference = "Stop"

$scriptPath = Join-Path $PSScriptRoot "start_app.ps1"
$desktopPath = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktopPath "CareerSignal HH.lnk"

if (-not (Test-Path $scriptPath)) {
    Write-Host "ERROR: start_app.ps1 not found at $scriptPath" -ForegroundColor Red
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
$Shortcut.Description = "CareerSignal HH — Local App"
$Shortcut.Save()

Write-Host "Shortcut created on Desktop: CareerSignal HH.lnk" -ForegroundColor Green
Write-Host "Double-click to start the local app window." -ForegroundColor Green
Write-Host ""
Write-Host "Fallback browser UI:" -ForegroundColor Gray
Write-Host "  powershell -ExecutionPolicy Bypass -File `"$PSScriptRoot\start_ui.ps1`"" -ForegroundColor Gray
