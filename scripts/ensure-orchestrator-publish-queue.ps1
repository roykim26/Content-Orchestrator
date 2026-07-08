param(
    [ValidateSet("note", "ameba", "hatena", "zenn")]
    [string]$Platform,
    [string]$Account = "",
    [int]$TopicLimit = 20
)

$ErrorActionPreference = "Stop"
$baseUrl = "http://127.0.0.1:8020"

function Invoke-Json {
    param(
        [string]$Uri,
        [string]$Method = "GET",
        [object]$Body = $null,
        [int]$TimeoutSec = 30
    )

    $params = @{
        Uri = $Uri
        Method = $Method
        TimeoutSec = $TimeoutSec
    }
    if ($null -ne $Body) {
        $params.ContentType = "application/json"
        $params.Body = ($Body | ConvertTo-Json -Depth 12)
    }
    return Invoke-RestMethod @params
}

function Get-AccountAliases {
    if (-not $Account) {
        return @()
    }
    $aliases = @($Account)
    if ($Platform -eq "hatena") {
        if ($Account -eq "A") {
            $aliases += "note_a"
        } elseif ($Account -eq "B") {
            $aliases += "note_b"
        } elseif ($Account -eq "note_a") {
            $aliases += "A"
        } elseif ($Account -eq "note_b") {
            $aliases += "B"
        }
    }
    return $aliases | Select-Object -Unique
}

function Test-ArtifactAccount {
    param([object]$Artifact)

    if (-not $Account) {
        return $true
    }
    $aliases = @(Get-AccountAliases)
    $artifactAccounts = @($Artifact.metadata.account)
    if ($Platform -eq "note" -or $Platform -eq "hatena") {
        $artifactAccounts += $Artifact.metadata.note_account
    }
    foreach ($artifactAccount in $artifactAccounts) {
        if ($artifactAccount -and $artifactAccount -in $aliases) {
            return $true
        }
    }
    return $false
}

function Test-TopicAccount {
    param([object]$Topic)

    if (-not $Account) {
        return $true
    }
    if ($Platform -ne "note" -and $Platform -ne "hatena") {
        return $true
    }
    $aliases = @(Get-AccountAliases)
    return ($Topic.note_account -in $aliases)
}

function Get-PendingArtifact {
    $artifacts = Invoke-Json -Uri "$baseUrl/artifacts?status=publish_pending" -TimeoutSec 15
    foreach ($artifact in @($artifacts)) {
        if ($artifact.platform -ne $Platform) {
            continue
        }
        if (-not (Test-ArtifactAccount -Artifact $artifact)) {
            continue
        }
        return $artifact
    }
    return $null
}

function Get-RetryableFailedArtifact {
    $cutoff = (Get-Date).AddDays(-7)
    $artifacts = Invoke-Json -Uri "$baseUrl/artifacts?status=failed" -TimeoutSec 15
    foreach ($artifact in @($artifacts)) {
        if ($artifact.platform -ne $Platform) {
            continue
        }
        if ($artifact.reviewed -ne $true) {
            continue
        }
        if ([int]$artifact.publish_attempts -ge 2) {
            continue
        }
        if ([datetime]$artifact.updated_at -lt $cutoff) {
            continue
        }
        if (-not (Test-ArtifactAccount -Artifact $artifact)) {
            continue
        }
        return $artifact
    }
    return $null
}

function Get-TopicTask {
    param([string]$TopicId)

    $overview = Invoke-Json -Uri "$baseUrl/topics/$TopicId/overview" -TimeoutSec 15
    if (@($overview.tasks).Count -eq 0 -and $overview.topic.status -eq "ready") {
        Invoke-Json -Uri "$baseUrl/topics/$TopicId/plan" -Method "POST" -TimeoutSec 30 | Out-Null
        $overview = Invoke-Json -Uri "$baseUrl/topics/$TopicId/overview" -TimeoutSec 15
    }

    foreach ($task in @($overview.tasks)) {
        if ($task.platform -eq $Platform -and $task.status -eq "pending") {
            return $task
        }
    }
    return $null
}

$existing = Get-PendingArtifact
if ($null -ne $existing) {
    Write-Output "publish_pending already available: $($existing.id)"
    exit 0
}

$failed = Get-RetryableFailedArtifact
if ($null -ne $failed) {
    $requeueBody = @{
        requested_by = "ensure-orchestrator-publish-queue"
        reason = "auto requeue failed publish artifact before scheduled trigger"
        clear_error = $true
    }
    $requeued = Invoke-Json -Uri "$baseUrl/artifacts/$($failed.id)/requeue" -Method "POST" -Body $requeueBody -TimeoutSec 30
    Write-Output "requeued failed $Platform artifact: $($requeued.id)"
    exit 0
}

Invoke-Json -Uri "$baseUrl/topics/sync-feishu?plan=false&dry_run=false&skip_existing=true&status=ready&limit=$TopicLimit" -Method "POST" -TimeoutSec 60 | Out-Null

$topics = Invoke-Json -Uri "$baseUrl/topics?status=ready" -TimeoutSec 15
$topics += Invoke-Json -Uri "$baseUrl/topics?status=planned" -TimeoutSec 15

foreach ($topic in @($topics)) {
    if ($Platform -notin @($topic.target_platforms)) {
        continue
    }
    if (-not (Test-TopicAccount -Topic $topic)) {
        continue
    }

    $task = Get-TopicTask -TopicId $topic.id
    if ($null -eq $task) {
        continue
    }

    Write-Output "running generation task $($task.id) for $Platform from topic $($topic.id)"
    $result = Invoke-Json -Uri "$baseUrl/tasks/$($task.id)/run" -Method "POST" -TimeoutSec 240
    if (-not $result.artifact_id) {
        throw "Generation task $($task.id) did not return artifact_id."
    }

    if ($Platform -in @("note", "ameba", "hatena", "zenn")) {
        Invoke-Json -Uri "$baseUrl/artifacts/$($result.artifact_id)/approve" -Method "POST" -TimeoutSec 30 | Out-Null
    }

    $queued = Get-PendingArtifact
    if ($null -ne $queued) {
        Write-Output "queued $Platform artifact: $($queued.id)"
        exit 0
    }

    throw "Generated artifact $($result.artifact_id), but it was not publish_pending."
}

Write-Output "No eligible $Platform topic/task found to queue."
exit 0
