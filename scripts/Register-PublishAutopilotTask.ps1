param(
    [string]$TaskName = "content-orchestrator-publish-autopilot",
    [int]$IntervalMinutes = 30,
    [switch]$StartNow
)

$ErrorActionPreference = "Stop"

if ($IntervalMinutes -lt 5) {
    throw "IntervalMinutes must be at least 5."
}

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$script = Join-Path $root "scripts\invoke-publish-autopilot.ps1"
$powershellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"

if (-not (Test-Path $script)) {
    throw "Publish autopilot script not found: $script"
}

$action = New-ScheduledTaskAction `
    -Execute $powershellExe `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`"" `
    -WorkingDirectory $root

$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

$task = New-ScheduledTask `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Runs Content Orchestrator publish autopilot for note_a, note_b, and Ameba."

Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null

Write-Output "Registered task: $TaskName"
Write-Output "Interval: every $IntervalMinutes minutes"
Write-Output "Action: $powershellExe -NoProfile -ExecutionPolicy Bypass -File `"$script`""

if ($StartNow) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Output "Started task: $TaskName"
}
