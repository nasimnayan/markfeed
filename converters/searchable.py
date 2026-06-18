"""Build a searchable PDF: original-looking pages with an invisible OCR text layer.

Each page becomes a single-page PDF — OCR pages via Tesseract's PDF output (image +
hidden text), digital pages by copying the original page (which already has real
text). The worker collects these per-page PDFs and merges them in page order. The
text layer aligns with the embedded image because Tesseract OCRs and embeds the
same image, so search-highlighting lands in the right place.
"""

from pathlib import Path

import fitz  # PyMuPDF
import pytesseract
from PIL import Image

from converters import tesseract_config  # noqa: F401  (sets tesseract cmd + PATH)

# Cap the embedded page image so the output PDF size (and the text-layer OCR pass)
# stays reasonable. 2600px on the long side keeps 300-DPI A4 legible.
_MAX_EMBED_DIM = 2600


def page_pdf_from_image(img: Image.Image, lang: str) -> bytes:
    """Single-page searchable PDF for an OCR page (image + invisible text layer)."""
    embed = img
    if max(img.size) > _MAX_EMBED_DIM:
        embed = img.copy()
        embed.thumbnail((_MAX_EMBED_DIM, _MAX_EMBED_DIM))
    return pytesseract.image_to_pdf_or_hocr(embed, extension="pdf", lang=lang)


def page_pdf_from_pdf_page(doc: fitz.Document, page_index: int) -> bytes:
    """Single-page PDF copied from an already-text-bearing (digital) source page."""
    single = fitz.open()
    try:
        single.insert_pdf(doc, from_page=page_index, to_page=page_index)
        return single.tobytes()
    finally:
        single.close()


def merge_to_file(page_pdf_paths: list[Path], out_path: Path) -> None:
    """Merge per-page PDFs (already in reading order) into one searchable PDF."""
    merged = fitz.open()
    try:
        for path in page_pdf_paths:
            with fitz.open(path) as src:
                merged.insert_pdf(src)
        merged.save(str(out_path))
    finally:
        merged.close()
