param(
    [string]$NotePublisherRoot = "",
    [string]$CdpUrl = "http://127.0.0.1:9222"
)

$ErrorActionPreference = "Stop"

if (-not $NotePublisherRoot) {
    $NotePublisherRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..\note-auto-publisher")).Path
}

function Backup-File {
    param([string]$Path)
    $backup = "$Path.cdp_fallback_backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
    Copy-Item -LiteralPath $Path -Destination $backup -Force
    Write-Host "backup: $backup"
}

function Write-Utf8NoBom {
    param(
        [string]$Path,
        [string]$Text
    )
    [System.IO.File]::WriteAllText($Path, $Text, [System.Text.UTF8Encoding]::new($false))
}

$configPath = Join-Path $NotePublisherRoot "app\config.py"
$publisherPath = Join-Path $NotePublisherRoot "app\note_publisher.py"
$batchPath = Join-Path $NotePublisherRoot "_run_note_auto_publisher_orch_publish.bat"

foreach ($path in @($configPath, $publisherPath, $batchPath)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "missing file: $path"
    }
}

Backup-File -Path $configPath
Backup-File -Path $publisherPath
Backup-File -Path $batchPath

$config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8
if ($config -notmatch "note_playwright_cdp_url") {
    $needle = @'
    note_playwright_subprocess_timeout_seconds: int = Field(
        default=600,
        alias="NOTE_PLAYWRIGHT_SUBPROCESS_TIMEOUT_SECONDS",
    )
'@
    $replacement = @'
    note_playwright_subprocess_timeout_seconds: int = Field(
        default=600,
        alias="NOTE_PLAYWRIGHT_SUBPROCESS_TIMEOUT_SECONDS",
    )
    note_playwright_cdp_url: str = Field(default="", alias="NOTE_PLAYWRIGHT_CDP_URL")
'@
    if (-not $config.Contains($needle)) {
        throw "config insertion point not found"
    }
    $config = $config.Replace($needle, $replacement)
    Write-Utf8NoBom -Path $configPath -Text $config
    Write-Host "patched config.py"
} else {
    Write-Host "config.py already has NOTE_PLAYWRIGHT_CDP_URL"
}

$publisher = Get-Content -LiteralPath $publisherPath -Raw -Encoding UTF8
if ($publisher -notmatch "self\.cdp_url") {
    $needle = '        self.instance_label = _safe_str(getattr(self.settings, "app_instance_label", ""))'
    $replacement = @'
        self.instance_label = _safe_str(getattr(self.settings, "app_instance_label", ""))
        self.cdp_url = _safe_str(getattr(self.settings, "note_playwright_cdp_url", ""))
'@
    if (-not $publisher.Contains($needle)) {
        throw "publisher __init__ insertion point not found"
    }
    $publisher = $publisher.Replace($needle, $replacement.TrimEnd())
}

if ($publisher -notmatch "connect_over_cdp") {
    $pattern = '(?m)^    def _launch_browser\(self, p: Playwright\) -> Browser:\r?\n        return p\.chromium\.launch\(headless=self\.headless\)'
    $replacement = @'
    def _launch_browser(self, p: Playwright) -> Browser:
        if self.cdp_url:
            return p.chromium.connect_over_cdp(self.cdp_url)
        return p.chromium.launch(headless=self.headless)
'@
    if ($publisher -notmatch $pattern) {
        throw "publisher _launch_browser insertion point not found"
    }
    $publisher = [regex]::Replace($publisher, $pattern, $replacement.TrimEnd())
}

if ($publisher -notmatch "_close_context_and_browser") {
    $pattern = '(?ms)^    def _new_context\(self, browser: Browser, \*, use_storage_state: bool\) -> BrowserContext:\r?\n        kwargs: Dict\[str, Any\] = \{\r?\n            "viewport": \{"width": 1440, "height": 960\},\r?\n            "locale": "ja-JP",\r?\n            "permissions": \["clipboard-read", "clipboard-write"\],\r?\n        \}\r?\n        if use_storage_state and self\.storage_state_path\.exists\(\):\r?\n            kwargs\["storage_state"\] = str\(self\.storage_state_path\)\r?\n        return browser\.new_context\(\*\*kwargs\)'
    $replacement = @'
    def _new_context(self, browser: Browser, *, use_storage_state: bool) -> BrowserContext:
        kwargs: Dict[str, Any] = {
            "viewport": {"width": 1440, "height": 960},
            "locale": "ja-JP",
            "permissions": ["clipboard-read", "clipboard-write"],
        }
        if use_storage_state and self.storage_state_path.exists():
            kwargs["storage_state"] = str(self.storage_state_path)
        return browser.new_context(**kwargs)
'@
    $replacement = @'
    def _new_context(self, browser: Browser, *, use_storage_state: bool) -> BrowserContext:
        kwargs: Dict[str, Any] = {
            "viewport": {"width": 1440, "height": 960},
            "locale": "ja-JP",
            "permissions": ["clipboard-read", "clipboard-write"],
        }
        if self.cdp_url and browser.contexts:
            return browser.contexts[0]
        if use_storage_state and self.storage_state_path.exists():
            kwargs["storage_state"] = str(self.storage_state_path)
        return browser.new_context(**kwargs)

    def _close_context_and_browser(self, context: BrowserContext, browser: Browser) -> None:
        if self.cdp_url:
            return
        context.close()
        browser.close()
'@
    if ($publisher -notmatch $pattern) {
        throw "publisher _new_context insertion point not found"
    }
    $publisher = [regex]::Replace($publisher, $pattern, $replacement.TrimEnd())
}

$publisher = [regex]::Replace(
    $publisher,
    '(?m)^                context\.close\(\)\r?\n                browser\.close\(\)',
    '                self._close_context_and_browser(context, browser)'
)

Write-Utf8NoBom -Path $publisherPath -Text $publisher
Write-Host "patched note_publisher.py"

$batch = Get-Content -LiteralPath $batchPath -Raw -Encoding Default
if ($batch -notmatch "NOTE_PLAYWRIGHT_CDP_URL") {
    $needle = 'set "NOTE_PLAYWRIGHT_SUBPROCESS_TIMEOUT_SECONDS=900"'
    $replacement = @"
$needle
set "NOTE_PLAYWRIGHT_CDP_URL=$CdpUrl"
"@
    if (-not $batch.Contains($needle)) {
        throw "batch insertion point not found"
    }
    $batch = $batch.Replace($needle, $replacement.TrimEnd())
    Set-Content -LiteralPath $batchPath -Value $batch -Encoding Default
    Write-Host "patched _run_note_auto_publisher_orch_publish.bat"
} else {
    Write-Host "batch already has NOTE_PLAYWRIGHT_CDP_URL"
}

Write-Host "done. CDP URL: $CdpUrl"
