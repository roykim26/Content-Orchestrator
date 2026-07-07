param(
    [ValidateSet("Orchestrator", "Legacy")]
    [string]$Mode = "Orchestrator",
    [string]$OrchestratorRunAt = "14:30",
    [string]$LegacyStartAt = "14:20",
    [switch]$StartNow
)

$ErrorActionPreference = "Stop"

$taskName = "note-auto-publisher-ameba-publish"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$publisherRoot = Join-Path (Split-Path -Parent $root) "note-auto-publisher"
$powershellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"

function New-DailyTrigger {
    param([string]$At)

    $parts = $At.Split(":")
    if ($parts.Count -ne 2) {
        throw "Time must be HH:mm, got: $At"
    }

    $hour = [int]$parts[0]
    $minute = [int]$parts[1]
    if ($hour -lt 0 -or $hour -gt 23 -or $minute -lt 0 -or $minute -gt 59) {
        throw "Time must be HH:mm, got: $At"
    }

    $now = Get-Date
    $runAt = Get-Date -Hour $hour -Minute $minute -Second 0
    if ($runAt -lt $now) {
        $runAt = $runAt.AddDays(1)
    }
    return New-ScheduledTaskTrigger -Daily -At $runAt
}

if ($Mode -eq "Orchestrator") {
    $script = Join-Path $root "scripts\invoke-ameba-orch-publish.ps1"
    if (-not (Test-Path $script)) {
        throw "Orchestrator trigger script not found: $script"
    }
    $action = New-ScheduledTaskAction `
        -Execute $powershellExe `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`"" `
        -WorkingDirectory $root
    $trigger = New-DailyTrigger -At $OrchestratorRunAt
    $description = "Ameba daily publish via Content Orchestrator. Calls invoke-ameba-orch-publish.ps1."
} else {
    $legacyStart = Join-Path $publisherRoot "start_ameba_auto_publisher.bat"
    if (-not (Test-Path $legacyStart)) {
        throw "Legacy Ameba start script not found: $legacyStart"
    }
    $action = New-ScheduledTaskAction `
        -Execute "cmd.exe" `
        -Argument "/c `"$legacyStart`"" `
        -WorkingDirectory $publisherRoot
    $trigger = New-DailyTrigger -At $LegacyStartAt
    $description = "Ameba legacy publisher mode. Starts the existing 8011 Ameba service; its internal scheduler handles publishing."
}

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

$task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description $description
Register-ScheduledTask -TaskName $taskName -InputObject $task -Force | Out-Null

Write-Output "Ameba publisher mode set to $Mode."
Write-Output "Task: $taskName"
if ($Mode -eq "Orchestrator") {
    Write-Output "Schedule: daily at $OrchestratorRunAt local time"
    Write-Output "Action: $powershellExe -NoProfile -ExecutionPolicy Bypass -File `"$script`""
    if ($StartNow) {
        & $script
    }
} else {
    Write-Output "Schedule: daily at $LegacyStartAt local time"
    Write-Output "Action: cmd.exe /c `"$legacyStart`""
    if ($StartNow) {
        & $legacyStart
    }
}
