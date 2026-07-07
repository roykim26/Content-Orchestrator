param(
    [switch]$DryRun,
    [switch]$Force,
    [switch]$NoFeishu,
    [int]$TimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$pythonExe = "C:\Users\jinlo\AppData\Local\Python\pythoncore-3.14-64\python.exe"
$logDir = Join-Path $root "logs"
$publisherEnv = Join-Path (Split-Path -Parent $root) "note-auto-publisher\.env"

if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logPath = Join-Path $logDir "topic_refill_$timestamp.log"

function Write-Log {
    param([string]$Message)
    $line = "$(Get-Date -Format "yyyy-MM-dd HH:mm:ss") $Message"
    Add-Content -Path $logPath -Value $line -Encoding UTF8
    Write-Output $line
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

$dryRunValue = if ($DryRun.IsPresent) { "True" } else { "False" }
$forceValue = if ($Force.IsPresent) { "True" } else { "False" }
$writeToFeishuValue = if ($NoFeishu.IsPresent) { "False" } else { "True" }

Write-Log "Starting topic refill. dry_run=$dryRunValue force=$forceValue write_to_feishu=$writeToFeishuValue"

$code = @"
from sqlmodel import Session
from app.db import engine
from app.services.topic_refill_service import TopicRefillService
import json

with Session(engine) as session:
    result = TopicRefillService(session).run_refill(
        dry_run=$dryRunValue,
        force=$forceValue,
        write_to_feishu=$writeToFeishuValue,
    )
print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
"@

$output = & $pythonExe -c $code
if ($LASTEXITCODE -ne 0) {
    $output | ForEach-Object { Write-Log $_ }
    exit $LASTEXITCODE
}
$output | ForEach-Object { Write-Log $_ }

Write-Log "Topic refill finished. Log: $logPath"
