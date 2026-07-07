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

$backup = "$publisherPath.formatting_backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
Copy-Item -LiteralPath $publisherPath -Destination $backup -Force
Write-Host "backup: $backup"

$py = @'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")

def replace_span(source: str, start_marker: str, end_marker: str, replacement: str) -> str:
    start = source.find(start_marker)
    if start < 0:
        raise SystemExit(f"start marker not found: {start_marker}")
    end = source.find(end_marker, start)
    if end < 0:
        raise SystemExit(f"end marker not found: {end_marker}")
    return source[:start] + replacement.rstrip() + "\n\n" + source[end:]

publish_selector_block = '''
    def _find_publish_settings_button(self, page: Page) -> Optional[Locator]:
        advance = "\\u516c\\u958b\\u306b\\u9032\\u3080"
        settings = "\\u516c\\u958b\\u8a2d\\u5b9a"
        selectors = [
            f'button:has-text("{advance}")',
            f'[role="button"]:has-text("{advance}")',
            f'button:has-text("{settings}")',
            f'[role="button"]:has-text("{settings}")',
        ]

        for selector in selectors:
            locator = page.locator(selector)
            try:
                if locator.count() > 0 and locator.first.is_visible():
                    return locator.first
            except Exception:
                continue

        return None

    def _find_final_publish_button(self, page: Page) -> Optional[Locator]:
        post = "\\u6295\\u7a3f\\u3059\\u308b"
        publish = "\\u516c\\u958b\\u3059\\u308b"
        update = "\\u66f4\\u65b0\\u3059\\u308b"
        publish_word = "\\u516c\\u958b"
        post_word = "\\u6295\\u7a3f"
        update_word = "\\u66f4\\u65b0"
        advance = "\\u516c\\u958b\\u306b\\u9032\\u3080"
        draft_save = "\\u4e0b\\u66f8\\u304d\\u4fdd\\u5b58"
        save = "\\u4fdd\\u5b58"
        cancel = "\\u30ad\\u30e3\\u30f3\\u30bb\\u30eb"
        back = "\\u623b\\u308b"
        delete = "\\u524a\\u9664"

        selectors = [
            f'button:has-text("{post}")',
            f'[role="button"]:has-text("{post}")',
            f'button:has-text("{publish}")',
            f'[role="button"]:has-text("{publish}")',
            f'button:has-text("{update}")',
            f'[role="button"]:has-text("{update}")',
            f'input[type="submit"][value*="{publish_word}"]',
            f'button:has-text("{publish_word}")',
            f'[role="button"]:has-text("{publish_word}")',
        ]

        for selector in selectors:
            locator = page.locator(selector)
            try:
                count = locator.count()
            except Exception:
                count = 0

            for i in range(count):
                candidate = locator.nth(i)
                try:
                    if not candidate.is_visible():
                        continue
                    if not candidate.is_enabled():
                        continue
                except Exception:
                    continue

                try:
                    label = _safe_str(candidate.inner_text()) or _safe_str(candidate.text_content())
                except Exception:
                    label = ""

                if advance in label:
                    continue

                return candidate

        generic_buttons = page.locator('button,[role="button"],input[type="submit"],a[role="button"]')
        try:
            count = generic_buttons.count()
        except Exception:
            count = 0

        candidates = []
        for i in range(count):
            candidate = generic_buttons.nth(i)
            try:
                if not candidate.is_visible():
                    continue
                if not candidate.is_enabled():
                    continue
            except Exception:
                continue

            try:
                label = " ".join(
                    [
                        _safe_str(candidate.inner_text()),
                        _safe_str(candidate.text_content()),
                        _safe_str(candidate.get_attribute("value")),
                        _safe_str(candidate.get_attribute("aria-label")),
                    ]
                )
            except Exception:
                label = ""

            normalized = re.sub(r"[\\s\\u3000]+", "", label)
            if not normalized:
                continue
            if any(bad in normalized for bad in [advance, draft_save, save, cancel, back, delete]):
                continue
            if not any(token in normalized for token in [post, publish, update, publish_word, post_word, update_word]):
                continue

            try:
                box = candidate.bounding_box()
            except Exception:
                box = None

            score = 0
            if post in normalized:
                score += 6
            elif publish in normalized:
                score += 5
            elif update in normalized:
                score += 5
            elif normalized == publish_word:
                score += 2
            elif normalized == post_word:
                score += 2
            elif normalized == update_word:
                score += 2

            if box:
                if box["y"] <= 140:
                    score += 3
                if box["x"] >= 850:
                    score += 2

            candidates.append((score, candidate))

        if not candidates:
            return None

        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]
'''

text = replace_span(
    text,
    "    def _find_publish_settings_button(self, page: Page) -> Optional[Locator]:",
    "    def _click_final_publish_with_retry(self, page: Page, draft_url: str) -> None:",
    publish_selector_block + "\n",
)

heading_pattern = re.compile(
    r'(\n            if block_type == "h2":\n'
    r'                self\._insert_heading_block\(page, locator, block, .+?\)\n'
    r'                if not is_last_block:\n)'
    r'                    page\.keyboard\.press\("Enter"\)'
    r'(\n                page\.wait_for_timeout\(180\)\n'
    r'                continue\n\n'
    r'            if block_type == "h3":\n'
    r'                self\._insert_heading_block\(page, locator, block, .+?\)\n'
    r'                if not is_last_block:\n)'
    r'                    page\.keyboard\.press\("Enter"\)',
    re.S,
)
text, heading_count = heading_pattern.subn(
    r'\1                    self._start_plain_paragraph_after_heading(page, locator)\2                    self._start_plain_paragraph_after_heading(page, locator)',
    text,
    count=1,
)
if heading_count != 1 and "    def _start_plain_paragraph_after_heading(" not in text:
    raise SystemExit("heading loop block not found")

helper_marker = "    def _insert_block_type_from_menu(self, page: Page, locator, menu_label: str) -> bool:\n"
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
if helper_marker not in text:
    raise SystemExit("helper insertion marker not found")
if "    def _start_plain_paragraph_after_heading(" not in text:
    text = text.replace(helper_marker, helper + helper_marker, 1)

path.write_text(text, encoding="utf-8")
print("patched note_publisher.py formatting and publish selectors")
'@

$tmp = Join-Path $env:TEMP "fix_note_publisher_formatting.py"
[System.IO.File]::WriteAllText($tmp, $py, [System.Text.UTF8Encoding]::new($false))
& "C:\Users\jinlo\AppData\Local\Python\pythoncore-3.14-64\python.exe" -B $tmp $publisherPath
