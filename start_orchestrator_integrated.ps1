$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$publisherEnv = Join-Path (Split-Path -Parent $root) "note-auto-publisher\.env"

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

& "C:\Users\jinlo\AppData\Local\Python\pythoncore-3.14-64\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8020
