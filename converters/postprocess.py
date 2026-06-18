"""Markdown post-processing: table-of-contents generation.

`build_toc` scans the converted markdown for `#`-headings and prepends a linked
"## Contents" outline. Slugs are produced by `slugify`, which is also handed to
python-markdown's `toc` extension (in the web layer) so the preview's heading ids
match these anchors — for Bengali too (slugs keep Unicode word characters).

Headings only exist in layout-mode OCR and in DOCX/CSV output; plain whole-page OCR
is flat, so `build_toc` returns the text unchanged when there are no headings.
"""

import re
import unicodedata

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)


def slugify(value: str, separator: str = "-") -> str:
    """GitHub-ish, Unicode-safe slug (matches python-markdown's toc signature)."""
    value = unicodedata.normalize("NFC", value).strip().lower()
    value = re.sub(r"[^\w\s-]", "", value, flags=re.UNICODE)  # keep word chars + space + hyphen
    value = re.sub(r"[\s]+", separator, value)
    return value or "section"


def build_toc(markdown: str, max_level: int = 3) -> str:
    """Prepend a linked '## Contents' outline; return unchanged if no headings."""
    headings = [
        (len(m.group(1)), m.group(2).strip())
        for m in _HEADING_RE.finditer(markdown)
    ]
    headings = [(lvl, txt) for lvl, txt in headings if lvl <= max_level and txt]
    if not headings:
        return markdown

    min_lvl = min(lvl for lvl, _ in headings)
    seen: dict[str, int] = {}
    lines = ["## Contents", ""]
    for lvl, txt in headings:
        base = slugify(txt)
        # Mirror python-markdown's duplicate-id scheme (base, base_1, base_2 …).
        if base in seen:
            seen[base] += 1
            slug = f"{base}_{seen[base]}"
        else:
            seen[base] = 0
            slug = base
        indent = "  " * (lvl - min_lvl)
        lines.append(f"{indent}- [{txt}](#{slug})")

    return "\n".join(lines) + "\n\n" + markdown
