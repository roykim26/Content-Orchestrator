param(
    [ValidateSet("all", "note_a", "note_b", "ameba")]
    [string[]]$Lane = @("all"),
    [switch]$DryRun,
    [switch]$NoWait,
    [int]$WaitTimeoutSeconds = 900,
    [int]$PollIntervalSeconds = 10
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$logDir = Join-Path $root "logs"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logPath = Join-Path $logDir "publish_autopilot_$timestamp.log"
$orchestratorStarter = Join-Path $root "scripts\start-orchestrator-integrated-8020-once.ps1"
$noteTrigger = Join-Path $root "scripts\invoke-note-orch-publish.ps1"
$amebaTrigger = Join-Path $root "scripts\invoke-ameba-orch-publish.ps1"

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
        [int]$TimeoutSec = 30
    )

    return Invoke-RestMethod -Uri $Uri -Method $Method -TimeoutSec $TimeoutSec
}

function Ensure-Orchestrator {
    try {
        $health = Invoke-Json -Uri "http://127.0.0.1:8020/health" -TimeoutSec 5
        if ($health.status -eq "ok" -or $health.status -eq "healthy") {
            Write-Log "Content Orchestrator is healthy on 8020."
            return
        }
    } catch {
    }

    if (-not (Test-Path $orchestratorStarter)) {
        throw "Orchestrator starter not found: $orchestratorStarter"
    }
    Write-Log "Starting Content Orchestrator via $orchestratorStarter."
    & $orchestratorStarter | ForEach-Object { Write-Log "orchestrator: $_" }
}

function Ensure-PublisherLane {
    param([string]$LaneName)

    if ($LaneName -eq "note_a" -or $LaneName -eq "note_b") {
        if (-not (Test-Path $noteTrigger)) {
            throw "note trigger script not found: $noteTrigger"
        }
        Write-Log "Ensuring publisher service for $LaneName."
        & $noteTrigger -Account $LaneName -DryRun | ForEach-Object { Write-Log "$LaneName startup: $_" }
        return
    }

    if ($LaneName -eq "ameba") {
        if (-not (Test-Path $amebaTrigger)) {
            throw "Ameba trigger script not found: $amebaTrigger"
        }
        Write-Log "Ensuring publisher service for Ameba."
        & $amebaTrigger -DryRun | ForEach-Object { Write-Log "ameba startup: $_" }
        return
    }

    throw "Unknown lane: $LaneName"
}

$lanes = @()
foreach ($item in $Lane) {
    if ($item -eq "all") {
        $lanes = @("note_a", "note_b", "ameba")
        break
    }
    $lanes += $item
}
$lanes = $lanes | Select-Object -Unique

Write-Log "Starting publish autopilot for lanes: $($lanes -join ', ')."
Ensure-Orchestrator

$apiLanes = @()
foreach ($laneName in $lanes) {
    if (!$DryRun.IsPresent -and ($laneName -eq "note_a" -or $laneName -eq "note_b")) {
        Write-Log "Running note lane directly with repaired trigger for $laneName."
        & $noteTrigger -Account $laneName | ForEach-Object { Write-Log "$laneName publish: $_" }
        continue
    }

    Ensure-PublisherLane -LaneName $laneName
    $apiLanes += $laneName
}

if ($apiLanes.Count -eq 0) {
    Write-Log "All requested lanes completed via direct publisher triggers."
    exit 0
}

$query = @()
foreach ($laneName in $apiLanes) {
    $query += "lanes=$([uri]::EscapeDataString($laneName))"
}
$query += "dry_run=$($DryRun.IsPresent.ToString().ToLowerInvariant())"
$query += "wait=$((!$NoWait.IsPresent).ToString().ToLowerInvariant())"
$query += "wait_timeout_seconds=$WaitTimeoutSeconds"
$query += "poll_interval_seconds=$PollIntervalSeconds"

$url = "http://127.0.0.1:8020/automation/publish-autopilot/run?$($query -join '&')"
Write-Log "Calling autopilot API: $url"
$result = Invoke-Json -Uri $url -Method "POST" -TimeoutSec ($WaitTimeoutSeconds + 120)
$resultJson = $result | ConvertTo-Json -Depth 20
Write-Log "Autopilot result: $resultJson"

$failed = @($result.results | Where-Object { $_.status -eq "failed" })
if ($failed.Count -gt 0) {
    exit 1
}

exit 0
