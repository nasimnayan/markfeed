"""Page limits for the heavy diagram + table extraction mode.

Plain-text OCR has no cap (a whole 700-page book at once is slow but stable).
Extraction mode is capped to a small batch so each run stays fast and bounds
crash exposure — never more than 20 pages, fewer for big books.
"""


def extraction_page_cap(total_pages: int) -> int:
    """Max pages per run when diagram + table extraction is enabled."""
    if total_pages <= 20:
        return total_pages
    if total_pages <= 200:
        return 20
    return 10
