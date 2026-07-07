param(
    [int]$Port = 9222,
    [string]$UserDataDir = "$env:LOCALAPPDATA\note-cdp-edge-profile"
)

$ErrorActionPreference = "Stop"

$edgeCandidates = @(
    "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "C:\Program Files\Microsoft\Edge\Application\msedge.exe"
)

$edge = $edgeCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $edge) {
    throw "Microsoft Edge executable not found."
}

New-Item -ItemType Directory -Path $UserDataDir -Force | Out-Null

$args = @(
    "--remote-debugging-port=$Port",
    "--user-data-dir=$UserDataDir",
    "--no-first-run",
    "--no-default-browser-check",
    "https://editor.note.com/new"
)

Start-Process -FilePath $edge -ArgumentList $args
Write-Host "started Edge CDP browser"
Write-Host "url: http://127.0.0.1:$Port"
Write-Host "profile: $UserDataDir"
