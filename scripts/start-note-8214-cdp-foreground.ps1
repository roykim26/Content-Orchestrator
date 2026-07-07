param(
    [string]$PublisherRoot = "",
    [string]$CdpUrl = "http://127.0.0.1:9222"
)

$ErrorActionPreference = "Stop"

if (-not $PublisherRoot) {
    $PublisherRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..\note-auto-publisher")).Path
}

$pythonExe = "C:\Users\jinlo\AppData\Local\Python\pythoncore-3.14-64\python.exe"
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "Python executable not found: $pythonExe"
}

$env:APP_RUN_MODE = "note"
$env:APP_PORT = "8214"
$env:APP_INSTANCE_LABEL = "8214_orch_publish"
$env:ORCHESTRATOR_MODE_ENABLED = "true"
$env:ORCHESTRATOR_BASE_URL = "http://127.0.0.1:8020"
$env:ORCHESTRATOR_CONSUMER_NAME = "note-auto-publisher-orch-publish-note-a"
$env:ORCHESTRATOR_CLAIM_LIMIT = "1"
$env:SQLITE_PATH = "storage/app_runtime_8214_orch_publish.db"
$env:DAILY_RUN_NOTE_ACCOUNT = "note_a"
$env:DAILY_RUN_CATCH_UP_ON_STARTUP = "false"
$env:NOTE_B_DAILY_RUN_ENABLED = "false"
$env:NOTE_B_DAILY_RUN_CATCH_UP_ON_STARTUP = "false"
$env:AMEBA_DAILY_RUN_ENABLED = "false"
$env:PUBLISH_CHECK_ENABLED = "false"
$env:NOTE_PLAYWRIGHT_SUBPROCESS_ENABLED = "true"
$env:NOTE_PLAYWRIGHT_SUBPROCESS_TIMEOUT_SECONDS = "900"
$env:NOTE_PLAYWRIGHT_CDP_URL = $CdpUrl
$env:NOTE_DRAFT_TITLE_INPUT_MAX_RETRIES = "0"
$env:NOTE_DRAFT_TITLE_INPUT_RETRY_DELAY_SECONDS = "5"
$env:NOTE_PUBLISH_MODE = "publish"
$env:PYTHONIOENCODING = "utf-8"

Set-Location -LiteralPath $PublisherRoot
Write-Host "Starting note 8214 foreground service with CDP: $CdpUrl"
Write-Host "Keep this PowerShell window open while publishing."
& $pythonExe -B -m uvicorn app.main:app --host 127.0.0.1 --port 8214
