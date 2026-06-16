# Smoke check for CareerSignal HH
# Run this before committing to verify basic functionality

Write-Host "=== CareerSignal HH Smoke Check ===" -ForegroundColor Cyan

$ErrorActionPreference = "Continue"

$steps = @(
    @("--help", "python -m src.main --help"),
    @("doctor", "python -m src.main doctor"),
    @("version", "python -m src.main version"),
    @("presets list", "python -m src.main presets list"),
    @("search dry-run", "python -m src.main search --dry-run --mode smoke"),
    @("db info", "python -m src.main db info"),
    @("db backup", "python -m src.main db backup"),
    @("sample-export", "python -m src.main sample-export"),
    @("export", "python -m src.main export"),
    @("pytest", "python -m pytest tests/ -q")
)

$failed = 0
foreach ($step in $steps) {
    $name = $step[0]
    $cmd = $step[1]
    Write-Host "`n[$name]" -ForegroundColor Yellow
    $result = Invoke-Expression $cmd 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  FAILED (exit code $LASTEXITCODE)" -ForegroundColor Red
        $failed++
    } else {
        Write-Host "  OK" -ForegroundColor Green
    }
}

Write-Host "`n=== $($steps.Count - $failed)/$($steps.Count) passed ===" -ForegroundColor $(if ($failed -eq 0) { "Green" } else { "Red" })
exit $failed
