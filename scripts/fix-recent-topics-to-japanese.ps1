$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$pythonExe = "C:\Users\jinlo\AppData\Local\Python\pythoncore-3.14-64\python.exe"
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

& $pythonExe (Join-Path $root "scripts\fix_recent_topics_to_japanese.py")
exit $LASTEXITCODE
