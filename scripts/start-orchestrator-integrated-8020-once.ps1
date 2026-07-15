$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$pythonExe = "C:\Users\jinlo\AppData\Local\Python\pythoncore-3.14-64\python.exe"
$healthUrl = "http://127.0.0.1:8020/health"
$logsDir = Join-Path $root "logs"
$publisherEnv = Join-Path (Split-Path -Parent $root) "note-auto-publisher\.env"

function Test-OrchestratorHealth {
    try {
        $response = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 3
        return $response.status -eq "ok"
    } catch {
        return $false
    }
}

if (Test-OrchestratorHealth) {
    Write-Output "Content Orchestrator is already healthy on 8020."
    return
}

if (!(Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir | Out-Null
}

if (Test-Path $publisherEnv) {
    Get-Content $publisherEnv -Encoding UTF8 | ForEach-Object {
        if ($_ -match "^(FEISHU_APP_ID|FEISHU_APP_SECRET|FEISHU_APP_TOKEN|FEISHU_TABLE_ID|FEISHU_NOTIFY_RECEIVE_ID_TYPE|FEISHU_NOTIFY_RECEIVE_ID|OPENAI_API_KEY|OPENAI_BASE_URL|OPENAI_MODEL)=(.*)$") {
            [Environment]::SetEnvironmentVariable($matches[1], $matches[2], "Process")
        }
    }
}

if ($env:FEISHU_APP_TOKEN) {
    $env:FEISHU_LEGACY_TOPIC_APP_TOKEN = $env:FEISHU_APP_TOKEN
}
if ($env:FEISHU_TABLE_ID) {
    $env:FEISHU_LEGACY_TOPIC_TABLE_ID = $env:FEISHU_TABLE_ID
}

$env:FEISHU_TOPIC_APP_TOKEN = "RqcTbRx11aX4Yvsj5ITcSEGtnAe"
$env:FEISHU_TOPIC_TABLE_ID = "tblRmJfu5dpBGPpt"
$env:ENABLE_TOPIC_SELECTION_SCHEDULER = "false"

$processPath = [Environment]::GetEnvironmentVariable("Path", "Process")
if (!$processPath) {
    $processPath = [Environment]::GetEnvironmentVariable("PATH", "Process")
}
[Environment]::SetEnvironmentVariable("PATH", $null, "Process")
if ($processPath) {
    [Environment]::SetEnvironmentVariable("Path", $processPath, "Process")
}

Start-Process `
    -FilePath $pythonExe `
    -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8020") `
    -WorkingDirectory $root `
    -WindowStyle Hidden

$deadline = (Get-Date).AddSeconds(25)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 1
    if (Test-OrchestratorHealth) {
        Write-Output "Content Orchestrator started and is healthy on 8020."
        return
    }
}

throw "Content Orchestrator did not become healthy on 8020."
