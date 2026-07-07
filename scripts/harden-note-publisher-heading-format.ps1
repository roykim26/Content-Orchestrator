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

$backup = "$publisherPath.heading_hardening_backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
Copy-Item -LiteralPath $publisherPath -Destination $backup -Force

$text = [System.IO.File]::ReadAllText($publisherPath, [System.Text.Encoding]::UTF8)

if ($text -notmatch "_insert_structured_body_html") {
    $replacement = @'
    def _paste_structured_body(self, page: Page, locator, markdown_text: str) -> None:
        locator.click()
        page.wait_for_timeout(200)
        blocks = self._markdown_to_blocks(markdown_text)
        if not self._insert_structured_body_html(page, locator, blocks):
            self._type_blocks_via_markdown_shortcuts(page, locator, blocks)
        page.wait_for_timeout(1200)
        self._assert_no_oversized_editor_headings(page, locator)

    def _insert_structured_body_html(self, page: Page, locator, blocks: List[Dict[str, Any]]) -> bool:
        blocks_to_write = [block for block in blocks if self._block_to_plaintext(block)]
        if not blocks_to_write:
            return True

        html_doc = "".join(self._block_to_html(block) for block in blocks_to_write)
        plain_text = "\n\n".join(
            plain for plain in (self._block_to_plaintext(block) for block in blocks_to_write) if plain
        )
        self._focus_editor_typing_position(locator)
        return self._insert_html_at_cursor(page, locator, html_doc, plain_text)

    def _type_blocks_via_markdown_shortcuts(self, page: Page, locator, blocks: List[Dict[str, Any]]) -> None:
'@

    $text = [regex]::Replace(
        $text,
        '(?s)    def _paste_structured_body\(.*?\r?\n    def _type_blocks_via_markdown_shortcuts\(.*?\) -> None:\r?\n',
        [System.Text.RegularExpressions.MatchEvaluator]{ param($m) $replacement },
        1
    )
}

if ($text -notmatch "plain_text = self\._block_to_plaintext\(block\)") {
    $text = [regex]::Replace(
        $text,
        '            self\._ensure_plain_paragraph_before_text\(page, locator\)\r?\n            locator\.press_sequentially\(self\._block_to_plaintext\(block\), delay=12\)\r?\n            if not is_last_block:\r?\n                page\.keyboard\.press\("Enter"\)\r?\n            page\.wait_for_timeout\(150\)',
        "            self._ensure_plain_paragraph_before_text(page, locator)`n            plain_text = self._block_to_plaintext(block)`n            if not self._insert_html_at_cursor(page, locator, self._block_to_html(block), plain_text):`n                locator.press_sequentially(plain_text, delay=12)`n            if not is_last_block:`n                page.keyboard.press(`"Enter`")`n            page.wait_for_timeout(150)",
        1
    )
}

if ($text -notmatch "const fragment = template\.content\.cloneNode") {
    $text = [regex]::Replace(
        $text,
        '                                const template = document\.createElement\("template"\);\r?\n                                template\.innerHTML = htmlDoc;\r?\n                                range\.deleteContents\(\);\r?\n                                range\.insertNode\(template\.content\.cloneNode\(true\)\);\r?\n                                selection\.removeAllRanges\(\);\r?\n                                inserted = true;',
        "                                const template = document.createElement(`"template`");`n                                template.innerHTML = htmlDoc;`n                                range.deleteContents();`n                                const fragment = template.content.cloneNode(true);`n                                const lastNode = fragment.lastChild;`n                                range.insertNode(fragment);`n                                if (lastNode) {`n                                    const nextRange = document.createRange();`n                                    nextRange.setStartAfter(lastNode);`n                                    nextRange.collapse(true);`n                                    selection.removeAllRanges();`n                                    selection.addRange(nextRange);`n                                }`n                                inserted = true;",
        1
    )
}

if ($text -notmatch "_assert_no_oversized_editor_headings") {
    $addition = @'
        except Exception:
            return False

    def _assert_no_oversized_editor_headings(self, page: Page, locator) -> None:
        oversized = self._find_oversized_editor_headings(page, locator)
        if oversized:
            preview = " / ".join(item[:80] for item in oversized[:3])
            raise NotePublishError(
                "note body formatting check failed: a body paragraph was inserted as a heading. "
                f"oversized_headings={preview}"
            )

    def _find_oversized_editor_headings(self, page: Page, locator) -> List[str]:
        try:
            values = locator.evaluate(
                """(el) => {
                    const compact = (value) => String(value || "").replace(/\\s+/g, "");
                    return Array.from(el.querySelectorAll("h1,h2,h3,h4,h5,h6"))
                        .map((node) => compact(node.innerText || node.textContent || ""))
                        .filter((text) => text.length > 90);
                }"""
            )
        except Exception:
            return []
        if not isinstance(values, list):
            return []
        return [_safe_str(value) for value in values if _safe_str(value)]

    def _remove_blank_blocks_before_first_body_image(self, page: Page, locator) -> None:
'@

    $text = [regex]::Replace(
        $text,
        '        except Exception:\r?\n            return False\r?\n\r?\n    def _remove_blank_blocks_before_first_body_image\(self, page: Page, locator\) -> None:\r?\n',
        [System.Text.RegularExpressions.MatchEvaluator]{ param($m) $addition },
        1
    )
}

foreach ($required in @(
    "_insert_structured_body_html",
    "plain_text = self._block_to_plaintext(block)",
    "const fragment = template.content.cloneNode",
    "_assert_no_oversized_editor_headings"
)) {
    if ($text -notmatch [regex]::Escape($required)) {
        throw "patch verification failed: $required"
    }
}

[System.IO.File]::WriteAllText($publisherPath, $text, [System.Text.UTF8Encoding]::new($false))
Write-Host "patched $publisherPath"
Write-Host "backup: $backup"
