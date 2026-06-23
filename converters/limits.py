"""Suggested batch size for the heavy diagram + table extraction mode.

This is NO LONGER a hard cap. Extraction is local and free; the user may
convert "all pages" or any range, exactly like plain mode. Because extraction
is slow and can segfault on very long books, the UI shows an advisory note
suggesting this batch size — but does not enforce it. Plain-text OCR has never
been capped (a whole 700-page book is slow but stable).
"""


def extraction_page_cap(total_pages: int) -> int:
    """Suggested (not enforced) pages-per-run for diagram + table extraction."""
    if total_pages <= 20:
        return total_pages
    if total_pages <= 200:
        return 20
    return 10
