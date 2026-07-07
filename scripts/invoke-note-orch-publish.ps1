param(
    [ValidateSet("note_a", "note_b")]
    [string]$Account = "note_a",
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
$logPath = Join-Path $logDir "note_orch_publish_${Account}_$timestamp.log"
$queueEnsurer = Join-Path $root "scripts\ensure-orchestrator-publish-queue.ps1"

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
                $health.note_publish_mode -eq "publish" -and
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

function Test-NoteCdpReady {
    try {
        Invoke-Json -Uri "$noteCdpUrl/json/version" -TimeoutSec 3 | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Start-NoteCdpBrowser {
    if (Test-NoteCdpReady) {
        Write-Log "note CDP browser is ready on $noteCdpUrl with profile $noteCdpUserDataDir."
        return
    }

    $edgeCandidates = @(
        "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "C:\Program Files\Microsoft\Edge\Application\msedge.exe"
    )
    $edge = $edgeCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $edge) {
        throw "Microsoft Edge executable not found; cannot start note CDP browser."
    }

    New-Item -ItemType Directory -Path $noteCdpUserDataDir -Force | Out-Null
    $edgeArgs = @(
        "--remote-debugging-port=$noteCdpPort",
        "--user-data-dir=$noteCdpUserDataDir",
        "--no-first-run",
        "--no-default-browser-check",
        "https://editor.note.com/new"
    )

    Write-Log "Starting note CDP browser on $noteCdpUrl with profile $noteCdpUserDataDir."
    Start-Process -FilePath $edge -ArgumentList $edgeArgs -WindowStyle Minimized | Out-Null

    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $deadline) {
        if (Test-NoteCdpReady) {
            Write-Log "note CDP browser became ready on $noteCdpUrl."
            return
        }
        Start-Sleep -Seconds 1
    }

    throw "note CDP browser did not become ready on $noteCdpUrl."
}

function Stop-ProcessTree {
    param([int[]]$RootProcessIds)

    if (-not $RootProcessIds -or $RootProcessIds.Count -eq 0) {
        return
    }

    $allProcesses = @(Get-CimInstance Win32_Process)
    $idsToStop = New-Object 'System.Collections.Generic.HashSet[int]'
    $queue = New-Object 'System.Collections.Generic.Queue[int]'

    foreach ($processId in $RootProcessIds) {
        if ($idsToStop.Add([int]$processId)) {
            $queue.Enqueue([int]$processId)
        }
    }

    while ($queue.Count -gt 0) {
        $parentId = $queue.Dequeue()
        foreach ($child in @($allProcesses | Where-Object { $_.ParentProcessId -eq $parentId })) {
            if ($idsToStop.Add([int]$child.ProcessId)) {
                $queue.Enqueue([int]$child.ProcessId)
            }
        }
    }

    $orderedIds = @($idsToStop) | Sort-Object -Descending
    foreach ($processId in $orderedIds) {
        try {
            Stop-Process -Id $processId -Force -ErrorAction Stop
        } catch {
        }
    }
}

function Stop-NoteCdpBrowser {
    $escapedUserDataDir = [regex]::Escape($noteCdpUserDataDir)
    $portPattern = "--remote-debugging-port=$noteCdpPort(\s|$)"
    $profilePattern = "--user-data-dir=(`"|')?$escapedUserDataDir(`"|')?(\s|$)"

    $rootProcesses = @(
        Get-CimInstance Win32_Process |
            Where-Object {
                $_.Name -eq "msedge.exe" -and
                $_.CommandLine -and
                ($_.CommandLine -match $portPattern -or $_.CommandLine -match $profilePattern)
            }
    )

    if ($rootProcesses.Count -eq 0) {
        Write-Log "No note CDP Edge process found for $noteCdpUrl / $noteCdpUserDataDir."
        return
    }

    $rootProcessIds = @($rootProcesses | ForEach-Object { [int]$_.ProcessId })
    Write-Log "Closing note CDP Edge process tree for ${noteCdpUrl}: $($rootProcessIds -join ', ')."
    Stop-ProcessTree -RootProcessIds $rootProcessIds

    Start-Sleep -Seconds 2
    if (Test-NoteCdpReady) {
        Write-Log "note CDP browser still responded on $noteCdpUrl after cleanup attempt."
    } else {
        Write-Log "note CDP browser closed on $noteCdpUrl."
    }
}

function Get-NextNotePublishArtifactId {
    try {
        $artifacts = @(
            Invoke-Json -Uri "http://127.0.0.1:8020/artifacts?platform=note&status=publish_pending" -TimeoutSec 10
        )
        $matchingArtifacts = @(
            $artifacts |
                Where-Object { $_.metadata.note_account -eq $Account } |
                Sort-Object -Property created_at
        )
        if ($matchingArtifacts.Count -gt 0) {
            return [string]$matchingArtifacts[0].id
        }
    } catch {
        Write-Log "Could not resolve next note artifact for ${Account}: $($_.Exception.Message)"
    }

    return $null
}

function Wait-NoteArtifactTerminal {
    param(
        [string]$ArtifactId,
        [int]$TimeoutSec = 900
    )

    if (-not $ArtifactId) {
        Write-Log "No note artifact id available; skipping artifact terminal wait."
        return $null
    }

    $terminalStatuses = @("published", "published_unverified", "draft_created", "failed", "rejected")
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $artifact = Invoke-Json -Uri "http://127.0.0.1:8020/artifacts/$ArtifactId" -TimeoutSec 10
            $status = [string]$artifact.status
            if ($terminalStatuses -contains $status) {
                Write-Log "Note artifact $ArtifactId reached terminal status: $status."
                return $artifact
            }
            Write-Log "Waiting for note artifact $ArtifactId; current status: $status."
        } catch {
            Write-Log "Could not poll note artifact ${ArtifactId}: $($_.Exception.Message)"
        }
        Start-Sleep -Seconds 10
    }

    Write-Log "Timed out waiting for note artifact $ArtifactId to reach terminal status."
    return $null
}

if ($Account -eq "note_a") {
    $port = 8217
    $label = "8217_orch_publish"
    $runner = Join-Path $publisherRoot "_run_note_auto_publisher_orch_publish.bat"
    $sqlitePath = "storage/app_runtime_8217_orch_publish.db"
    $consumerName = "note-auto-publisher-orch-publish-note-a"
    $noteCdpPort = 9222
    $noteCdpUserDataDir = Join-Path $env:LOCALAPPDATA "note-cdp-edge-profile"
} else {
    $port = 8215
    $label = "8215_orch_publish_note_b"
    $runner = Join-Path $publisherRoot "_run_note_auto_publisher_orch_publish_note_b.bat"
    $sqlitePath = "storage/app_runtime_8215_orch_publish_note_b.db"
    $consumerName = "note-auto-publisher-orch-publish-note-b"
    $noteCdpPort = 9223
    $noteCdpUserDataDir = Join-Path $env:LOCALAPPDATA "note-cdp-edge-profile-note-b"
}
$noteCdpUrl = "http://127.0.0.1:$noteCdpPort"
$pythonExe = "C:\Users\jinlo\AppData\Local\Python\pythoncore-3.14-64\python.exe"

function Start-NotePublisher {
    $env:APP_RUN_MODE = "note"
    $env:APP_PORT = [string]$port
    $env:APP_INSTANCE_LABEL = $label
    $env:ORCHESTRATOR_MODE_ENABLED = "true"
    $env:ORCHESTRATOR_BASE_URL = "http://127.0.0.1:8020"
    $env:ORCHESTRATOR_CONSUMER_NAME = $consumerName
    $env:ORCHESTRATOR_CLAIM_LIMIT = "1"
    $env:SQLITE_PATH = $sqlitePath
    $env:DAILY_RUN_NOTE_ACCOUNT = $Account
    $env:DAILY_RUN_CATCH_UP_ON_STARTUP = "false"
    $env:NOTE_B_DAILY_RUN_ENABLED = "false"
    $env:NOTE_B_DAILY_RUN_CATCH_UP_ON_STARTUP = "false"
    $env:AMEBA_DAILY_RUN_ENABLED = "false"
    $env:PUBLISH_CHECK_ENABLED = "false"
    $env:NOTE_PLAYWRIGHT_SUBPROCESS_ENABLED = "true"
    $env:NOTE_PLAYWRIGHT_SUBPROCESS_TIMEOUT_SECONDS = "900"
    $env:NOTE_PLAYWRIGHT_CDP_URL = $noteCdpUrl
    $env:NOTE_DRAFT_TITLE_INPUT_MAX_RETRIES = "0"
    $env:NOTE_DRAFT_TITLE_INPUT_RETRY_DELAY_SECONDS = "5"
    $env:NOTE_PUBLISH_MODE = "publish"

    Start-Process `
        -FilePath $pythonExe `
        -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", [string]$port) `
        -WorkingDirectory $publisherRoot `
        -WindowStyle Hidden
}

$exitCode = 0
$publishArtifactId = $null

try {
    Write-Log "Starting scheduled publish trigger for $Account."

    try {
        Invoke-Json -Uri "http://127.0.0.1:8020/health" -TimeoutSec 5 | Out-Null
        Write-Log "Content Orchestrator 8020 is healthy."
    } catch {
        throw "Content Orchestrator is not reachable on 127.0.0.1:8020. Start it before scheduled publishing. $($_.Exception.Message)"
    }

    Start-NoteCdpBrowser

    try {
        Wait-Healthy -Port $port -ExpectedLabel $label -TimeoutSec 5 | Out-Null
        Write-Log "$Account publish service is already healthy on port $port."
    } catch {
        Write-Log "$Account publish service is not ready; starting uvicorn directly."
        Start-NotePublisher
        Wait-Healthy -Port $port -ExpectedLabel $label -TimeoutSec 90 | Out-Null
        Write-Log "$Account publish service became healthy on port $port."
    }

    if ($DryRun) {
        Write-Log "Dry run completed; publish endpoint was not called."
        return
    }

    if (Test-Path $queueEnsurer) {
        Write-Log "Ensuring note publish queue for $Account."
        $queueOutput = & "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" `
            -NoProfile `
            -ExecutionPolicy Bypass `
            -File $queueEnsurer `
            -Platform note `
            -Account $Account
        foreach ($line in @($queueOutput)) {
            Write-Log "Queue ensure: $line"
            if ([string]$line -match "(publish_pending already available|queued note artifact|requeued failed note artifact):\s*(art_[A-Za-z0-9]+)") {
                $publishArtifactId = $Matches[2]
            }
        }
    }

    if (-not $publishArtifactId) {
        $publishArtifactId = Get-NextNotePublishArtifactId
        if ($publishArtifactId) {
            Write-Log "Resolved next note artifact for ${Account}: $publishArtifactId"
        }
    }

    $result = Invoke-Json -Uri "http://127.0.0.1:$port/ops/run-next-ready-draft" -Method "POST" -TimeoutSec 900
    $resultJson = $result | ConvertTo-Json -Depth 12
    Write-Log "Publish endpoint result: $resultJson"

    if ($result.ok -eq $false) {
        $exitCode = 1
    } elseif ($result.accepted -eq $true) {
        $finalArtifact = Wait-NoteArtifactTerminal -ArtifactId $publishArtifactId -TimeoutSec 900
        if ($finalArtifact -and @("failed", "rejected") -contains [string]$finalArtifact.status) {
            $exitCode = 1
        }
    }
} catch {
    $exitCode = 1
    Write-Log "Publish trigger failed for ${Account}: $($_.Exception.Message)"
} finally {
    try {
        Stop-NoteCdpBrowser
    } catch {
        Write-Log "Failed to close note CDP browser for ${Account}: $($_.Exception.Message)"
        if ($exitCode -eq 0) {
            $exitCode = 1
        }
    }
}

exit $exitCode
