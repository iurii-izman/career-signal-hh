# CareerSignal HH — Windows app-mode runner
# Run: powershell -ExecutionPolicy Bypass -File .\scripts\start_app.ps1

[CmdletBinding()]
param(
    [int]$Port = 8765,
    [string]$BindHost = "127.0.0.1",
    [ValidateSet("auto", "edge", "chrome")]
    [string]$Browser = "auto",
    [int]$StartupTimeoutSeconds = 45,
    [switch]$SmokeTest
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptRoot "..")).Path
$logsDir = Join-Path $repoRoot "logs"
$dataDir = Join-Path $repoRoot "data"
$statusPath = Join-Path $dataDir "ui_status.json"

function Resolve-CareerSignalPython {
    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        return @{ FilePath = $venvPython; Prefix = @() }
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return @{ FilePath = $python.Source; Prefix = @() }
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return @{ FilePath = $py.Source; Prefix = @("-3") }
    }

    throw "Python 3.11+ not found. Create .venv or add python to PATH."
}

function Resolve-AppBrowser {
    param([string]$RequestedBrowser)

    $known = @{
        edge = @(
            "$Env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
            "${Env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
        )
        chrome = @(
            "$Env:ProgramFiles\Google\Chrome\Application\chrome.exe",
            "${Env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
            "$Env:LocalAppData\Google\Chrome\Application\chrome.exe"
        )
    }

    $order = if ($RequestedBrowser -eq "auto") { @("edge", "chrome") } else { @($RequestedBrowser) }

    foreach ($name in $order) {
        foreach ($candidate in $known[$name]) {
            if ($candidate -and (Test-Path $candidate)) {
                return @{ Name = $name; Path = $candidate }
            }
        }
    }

    throw "No supported app-mode browser found. Install Microsoft Edge or Google Chrome."
}

function Wait-UiReady {
    param(
        [string]$Url,
        [int]$TimeoutSeconds,
        [System.Diagnostics.Process]$ServerProcess
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if ($ServerProcess.HasExited) {
            throw "UI server exited before becoming ready."
        }
        try {
            $response = Invoke-WebRequest -Uri "$Url/api/health" -UseBasicParsing -TimeoutSec 3
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return
            }
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    throw "UI did not become ready within ${TimeoutSeconds}s."
}

function Stop-UiServer {
    param([System.Diagnostics.Process]$ServerProcess)

    if (-not $ServerProcess) {
        return
    }
    if ($ServerProcess.HasExited) {
        return
    }

    try {
        Stop-Process -Id $ServerProcess.Id
        $ServerProcess.WaitForExit(5000) | Out-Null
    } catch {
        try {
            Stop-Process -Id $ServerProcess.Id -Force
        } catch {
        }
    }
}

function Update-UiStatusState {
    param(
        [string]$StatusFile,
        [string]$State,
        [int]$Port,
        [string]$StatusHost,
        [string]$Url,
        [string]$ProjectRoot,
        [string]$Version,
        [bool]$OpenBrowser
    )

    try {
        $status = [ordered]@{
            state = $State
            server_started_at = (Get-Date).ToUniversalTime().ToString("o")
            port = $Port
            host = $StatusHost
            url = $Url
            version = $Version
            pid = $PID
            cwd = $ProjectRoot
            project_root = $ProjectRoot
            open_browser = $OpenBrowser
            hostname = $Env:COMPUTERNAME
        }
        if ($State -eq "stopped") {
            $status["stopped_at"] = (Get-Date).ToUniversalTime().ToString("o")
        }
        $status | ConvertTo-Json -Depth 8 | Set-Content -Path $StatusFile -Encoding UTF8
    } catch {
        Write-Warning "Failed to write UI runtime status: $($_.Exception.Message)"
    }
}

New-Item -ItemType Directory -Force -Path $logsDir | Out-Null
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null

$python = Resolve-CareerSignalPython
$browserInfo = $null
if (-not $SmokeTest) {
    $browserInfo = Resolve-AppBrowser -RequestedBrowser $Browser
}
$urlHost = if ($BindHost -eq "0.0.0.0") { "127.0.0.1" } else { $BindHost }
if ($urlHost.Contains(":") -and -not $urlHost.StartsWith("[")) {
    $urlHost = "[$urlHost]"
}
$url = "http://${urlHost}:$Port"
$serverLog = Join-Path $logsDir ("app_server_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".log")
$serverErrLog = Join-Path $logsDir ("app_server_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".err.log")
$browserLog = Join-Path $logsDir ("app_browser_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".log")
$browserErrLog = Join-Path $logsDir ("app_browser_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".err.log")
$version = "unknown"
try {
    $version = (Get-Content (Join-Path $repoRoot "src\__init__.py") | Select-String '__version__ = "(.+)"').Matches[0].Groups[1].Value
} catch {
}
$serverArgs = @()
$serverArgs += $python.Prefix
$serverArgs += @("-m", "src.main", "ui", "--host", $BindHost, "--port", "$Port", "--no-browser")

$serverProcess = $null
try {
    Write-Host "Repo: $repoRoot"
    Write-Host "Server log: $serverLog"
    if ($SmokeTest) {
        Write-Host "Mode: smoke test"
    } else {
        Write-Host "Browser: $($browserInfo.Name) ($($browserInfo.Path))"
        Write-Host "Browser log: $browserLog"
    }

    $serverProcess = Start-Process `
        -FilePath $python.FilePath `
        -ArgumentList $serverArgs `
        -WorkingDirectory $repoRoot `
        -RedirectStandardOutput $serverLog `
        -RedirectStandardError $serverErrLog `
        -PassThru `
        -WindowStyle Hidden

    Wait-UiReady -Url $url -TimeoutSeconds $StartupTimeoutSeconds -ServerProcess $serverProcess
    Write-Host "UI ready at $url"

    if ($SmokeTest) {
        return
    }

    $browserArgs = @("--app=$url")
    $browserProcess = Start-Process `
        -FilePath $browserInfo.Path `
        -ArgumentList $browserArgs `
        -WorkingDirectory $repoRoot `
        -RedirectStandardOutput $browserLog `
        -RedirectStandardError $browserErrLog `
        -PassThru

    $browserProcess.WaitForExit()
} finally {
    Stop-UiServer -ServerProcess $serverProcess
    Update-UiStatusState `
        -StatusFile $statusPath `
        -State "stopped" `
        -Port $Port `
        -StatusHost $BindHost `
        -Url $url `
        -ProjectRoot $repoRoot `
        -Version $version `
        -OpenBrowser (-not $SmokeTest)
    if (Test-Path $statusPath) {
        Write-Host "Runtime status: $statusPath"
    }
}
