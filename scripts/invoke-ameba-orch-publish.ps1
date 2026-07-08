param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$publisherRoot = Join-Path (Split-Path -Parent $root) "note-auto-publisher"
$logDir = Join-Path $root "logs"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logPath = Join-Path $logDir "ameba_orch_publish_$timestamp.log"
$port = 8216
$label = "8216_orch_publish_ameba"
$runner = Join-Path $publisherRoot "_run_ameba_auto_publisher_orch_publish.bat"
$orchestratorRunner = Join-Path $root "start_orchestrator_integrated.ps1"
$queueEnsurer = Join-Path $root "scripts\ensure-orchestrator-publish-queue.ps1"
$pythonExe = "C:\Users\jinlo\AppData\Local\Python\pythoncore-3.14-64\python.exe"

function Write-Log {
    param([string]$Message)
    $line = "$(Get-Date -Format "yyyy-MM-dd HH:mm:ss") $Message"
    Add-Content -Path $logPath -Value $line -Encoding UTF8
    Write-Output $line
}

function Invoke-Json {
    param(
        [string]$Uri,
        [string]$Method = "GET",
        [int]$TimeoutSec = 10
    )

    return Invoke-RestMethod -Uri $Uri -Method $Method -TimeoutSec $TimeoutSec
}

function Wait-Healthy {
    param(
        [int]$Port,
        [string]$ExpectedLabel,
        [int]$TimeoutSec = 45
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $health = Invoke-Json -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 3
            if (
                $health.status -eq "healthy" -and
                $health.orchestrator_mode_enabled -eq $true -and
                $health.ameba_publish_mode -eq "publish" -and
                $health.app_instance_label -eq $ExpectedLabel
            ) {
                return $health
            }
        } catch {
        }
        Start-Sleep -Seconds 2
    }

    throw "Service on port $Port did not become healthy with label $ExpectedLabel."
}

function Wait-OrchestratorHealthy {
    param([int]$TimeoutSec = 60)

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $health = Invoke-Json -Uri "http://127.0.0.1:8020/health" -TimeoutSec 3
            if ($health.status -eq "ok" -or $health.status -eq "healthy") {
                return $health
            }
        } catch {
        }
        Start-Sleep -Seconds 2
    }

    throw "Content Orchestrator did not become healthy on 127.0.0.1:8020."
}

function Resolve-PlaywrightProxyServer {
    $configured = [Environment]::GetEnvironmentVariable("PLAYWRIGHT_PROXY_SERVER", "Process")
    if (-not [string]::IsNullOrWhiteSpace($configured) -and $configured -notmatch "127\.0\.0\.1:9(?:/)?$") {
        return $configured.Trim()
    }

    try {
        $internetSettings = Get-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings" -ErrorAction Stop
        if ($internetSettings.ProxyEnable -ne 1 -or [string]::IsNullOrWhiteSpace($internetSettings.ProxyServer)) {
            return ""
        }

        $proxyServer = [string]$internetSettings.ProxyServer
        if ($proxyServer -match "=") {
            $match = [regex]::Match($proxyServer, "(?:https?|socks)=([^;]+)")
            if ($match.Success) {
                $proxyServer = $match.Groups[1].Value
            } else {
                return ""
            }
        }

        $proxyServer = $proxyServer.Trim()
        if ($proxyServer -match "^[a-zA-Z][a-zA-Z0-9+.-]*://") {
            return $proxyServer
        }
        return "http://$proxyServer"
    } catch {
        return ""
    }
}

function Start-AmebaPublisher {
    $env:APP_RUN_MODE = "ameba"
    $env:APP_PORT = [string]$port
    $env:APP_INSTANCE_LABEL = $label
    $env:ORCHESTRATOR_MODE_ENABLED = "true"
    $env:ORCHESTRATOR_BASE_URL = "http://127.0.0.1:8020"
    $env:ORCHESTRATOR_CONSUMER_NAME = "ameba-auto-publisher-orch-publish"
    $env:ORCHESTRATOR_CLAIM_LIMIT = "1"
    $env:SQLITE_PATH = "storage/app_runtime_8216_orch_publish_ameba.db"
    $env:DAILY_RUN_CATCH_UP_ON_STARTUP = "false"
    $env:NOTE_B_DAILY_RUN_ENABLED = "false"
    $env:NOTE_B_DAILY_RUN_CATCH_UP_ON_STARTUP = "false"
    $env:AMEBA_DAILY_RUN_ENABLED = "false"
    $env:PUBLISH_CHECK_ENABLED = "false"
    $env:AMEBA_PUBLISH_MODE = "publish"
    $playwrightProxyServer = Resolve-PlaywrightProxyServer
    if ([string]::IsNullOrWhiteSpace($playwrightProxyServer)) {
        [Environment]::SetEnvironmentVariable("PLAYWRIGHT_PROXY_SERVER", $null, "Process")
        Write-Log "Ameba Playwright proxy: disabled."
    } else {
        $env:PLAYWRIGHT_PROXY_SERVER = $playwrightProxyServer
        Write-Log "Ameba Playwright proxy: enabled."
    }

    Start-Process `
        -FilePath $pythonExe `
        -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", [string]$port) `
        -WorkingDirectory $publisherRoot `
        -WindowStyle Hidden
}

Write-Log "Starting scheduled publish trigger for Ameba."

try {
    Invoke-Json -Uri "http://127.0.0.1:8020/health" -TimeoutSec 5 | Out-Null
    Write-Log "Content Orchestrator 8020 is healthy."
} catch {
    if (-not (Test-Path $orchestratorRunner)) {
        throw "Content Orchestrator is not reachable and runner script was not found: $orchestratorRunner. $($_.Exception.Message)"
    }
    Write-Log "Content Orchestrator 8020 is not reachable; starting $orchestratorRunner."
    Start-Process `
        -FilePath "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" `
        -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$orchestratorRunner`"" `
        -WorkingDirectory $root `
        -WindowStyle Hidden
    Wait-OrchestratorHealthy -TimeoutSec 75 | Out-Null
    Write-Log "Content Orchestrator 8020 became healthy."
}

try {
    Wait-Healthy -Port $port -ExpectedLabel $label -TimeoutSec 5 | Out-Null
    Write-Log "Ameba publish service is already healthy on port $port."
} catch {
    Write-Log "Ameba publish service is not ready; starting uvicorn directly."
    Start-AmebaPublisher
    Wait-Healthy -Port $port -ExpectedLabel $label -TimeoutSec 90 | Out-Null
    Write-Log "Ameba publish service became healthy on port $port."
}

if ($DryRun) {
    Write-Log "Dry run completed; publish endpoint was not called."
    exit 0
}

if (Test-Path $queueEnsurer) {
    Write-Log "Ensuring Ameba publish queue."
    $queueOutput = & "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" `
        -NoProfile `
        -ExecutionPolicy Bypass `
        -File $queueEnsurer `
        -Platform ameba
    foreach ($line in @($queueOutput)) {
        Write-Log "Queue ensure: $line"
    }
}

$result = Invoke-Json -Uri "http://127.0.0.1:$port/ops/ameba/run-next-ready-draft" -Method "POST" -TimeoutSec 900
$resultJson = $result | ConvertTo-Json -Depth 12
Write-Log "Publish endpoint result: $resultJson"

if ($result.ok -eq $false) {
    exit 1
}

exit 0
