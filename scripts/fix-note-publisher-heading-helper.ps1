param(
    [string]$PublisherRoot = ""
)

$ErrorActionPreference = "Stop"

if (-not $PublisherRoot) {
    $PublisherRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..\note-auto-publisher")).Path
}

$publisherPath = Join-Path $PublisherRoot "app\note_publisher.py"
if (-not (Test-Path -LiteralPath $publisherPath)) {
    throw "missing file: $publisherPath"
}

$backup = "$publisherPath.heading_helper_backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
Copy-Item -LiteralPath $publisherPath -Destination $backup -Force
Write-Host "backup: $backup"

$py = @'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")

if "    def _start_plain_paragraph_after_heading(" in text:
    print("heading helper already exists")
    raise SystemExit(0)

marker = "    def _insert_block_type_from_menu(self, page: Page, locator, menu_label: str) -> bool:\n"
if marker not in text:
    raise SystemExit("helper insertion marker not found")

helper = '''
    def _start_plain_paragraph_after_heading(self, page: Page, locator) -> None:
        page.keyboard.press("Enter")
        page.wait_for_timeout(120)
        self._reset_current_block_to_paragraph(page, locator)
        page.wait_for_timeout(80)

    def _reset_current_block_to_paragraph(self, page: Page, locator) -> None:
        paragraph_labels = [
            "\\u672c\\u6587",
            "\\u6bb5\\u843d",
            "\\u30c6\\u30ad\\u30b9\\u30c8",
            "\\u901a\\u5e38\\u30c6\\u30ad\\u30b9\\u30c8",
        ]
        menu_button = page.locator('button[aria-label="\\u30e1\\u30cb\\u30e5\\u30fc\\u3092\\u958b\\u304f"]')
        try:
            menu_button.click(timeout=2500)
        except Exception:
            try:
                locator.focus()
                menu_button.click(timeout=2500)
            except Exception:
                return

        page.wait_for_timeout(180)
        for label in paragraph_labels:
            try:
                button = page.get_by_role("button", name=label)
                if button.count() > 0 and button.first.is_visible():
                    button.first.click(timeout=2500)
                    page.wait_for_timeout(180)
                    locator.focus()
                    return
            except Exception:
                continue

        try:
            page.keyboard.press("Escape")
            locator.focus()
        except Exception:
            pass

'''

text = text.replace(marker, helper + marker, 1)
path.write_text(text, encoding="utf-8")
print("inserted heading paragraph reset helper")
'@

$tmp = Join-Path $env:TEMP "fix_note_publisher_heading_helper.py"
[System.IO.File]::WriteAllText($tmp, $py, [System.Text.UTF8Encoding]::new($false))
& "C:\Users\jinlo\AppData\Local\Python\pythoncore-3.14-64\python.exe" -B $tmp $publisherPath
