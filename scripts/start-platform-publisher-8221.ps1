param(
    [int]$Port = 8221
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location -LiteralPath $root

$env:APP_INSTANCE_LABEL = "8221_orch_publish_platforms"
if (-not $env:ORCHESTRATOR_BASE_URL) {
    $env:ORCHESTRATOR_BASE_URL = "http://127.0.0.1:8020"
}
if (-not $env:ORCHESTRATOR_CONSUMER_NAME) {
    $env:ORCHESTRATOR_CONSUMER_NAME = "platform-publisher-8221"
}
if (-not $env:ZENN_USERNAME) {
    $env:ZENN_USERNAME = "takkenai26"
}

python -m uvicorn app.platform_publishers.main:app --host 127.0.0.1 --port $Port
