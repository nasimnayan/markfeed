"""Convert PDF files (digital or scanned) to Markdown with per-page stats."""

import re
from pathlib import Path

import fitz  # PyMuPDF
import pymupdf4llm
import pytesseract
from PIL import Image

from converters import layout_ocr, tesseract_config  # noqa: F401  (sets tesseract path)
from converters.stats import count_formulas, count_images, count_md_tables, text_stats

DIGITAL_TEXT_THRESHOLD = 20  # min chars of extractable text to treat a page as "digital"


_IMAGE_LINK_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def _relativize_image_paths(markdown: str, images_dir: Path) -> str:
    """Rewrite absolute image paths produced by pymupdf4llm to images/<name>."""

    def repl(match: re.Match) -> str:
        alt, path = match.group(1), match.group(2)
        name = Path(path.replace("\\", "/")).name
        return f"![{alt}](images/{name})"

    return _IMAGE_LINK_RE.sub(repl, markdown)


def _save_preview(img: Image.Image, previews_dir: Path, page_index: int) -> str:
    """Save a downscaled JPEG of a rendered page for the side-by-side compare view.

    Kept small (max ~1240px wide, quality 82) so verification stays fast and
    storage stays light even for hundreds of pages. Lives outside images_dir so
    it is never embedded in the markdown or bundled in the download zip.
    """
    previews_dir.mkdir(parents=True, exist_ok=True)
    preview = img.copy()
    preview.thumbnail((1240, 1750))
    name = f"page_{page_index:04d}.jpg"
    preview.save(previews_dir / name, "JPEG", quality=82)
    return name


def convert_pdf(
    file_bytes: bytes,
    images_dir: Path,
    lang: str = "ben+eng",
    dpi: int = 300,
    use_layout: bool = True,
    start_page: int = 0,
    end_page: int | None = None,
    progress_callback=None,
    previews_dir: Path | None = None,
) -> dict:
    """Convert a PDF to Markdown.

    Returns a dict with keys: markdown (str), pages (list of per-page stat dicts).
    When previews_dir is given, a downscaled JPEG of each page is saved there and
    its filename recorded on the page row (for the side-by-side compare view).
    """
    images_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    total = len(doc)
    end = total if end_page is None else min(end_page, total)
    start = max(0, start_page)

    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    # Lower-res render just for previewing digital pages (which aren't otherwise
    # rasterised). Scanned pages reuse their full-res OCR render.
    preview_zoom = 150 / 72.0
    preview_matrix = fitz.Matrix(preview_zoom, preview_zoom)

    page_chunks = []
    page_rows = []

    for i in range(start, end):
        page = doc[i]
        text = page.get_text().strip()
        layout_counts = None
        rendered_img = None  # full-res render, reused for the preview when present

        if len(text) > DIGITAL_TEXT_THRESHOLD:
            page_md = pymupdf4llm.to_markdown(
                doc, pages=[i], write_images=True, image_path=str(images_dir)
            ).strip()
            page_md = _relativize_image_paths(page_md, images_dir)
            source = "digital"
        else:
            pix = page.get_pixmap(matrix=matrix)
            rendered_img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

            if use_layout:
                try:
                    page_md, layout_counts = layout_ocr.process_page_image(
                        rendered_img, lang, images_dir, i
                    )
                except Exception:
                    page_md = pytesseract.image_to_string(rendered_img, lang=lang).strip()
                    layout_counts = None
            else:
                page_md = pytesseract.image_to_string(rendered_img, lang=lang).strip()
                layout_counts = None

            source = "ocr"

        preview_name = None
        if previews_dir is not None:
            if rendered_img is None:  # digital page — rasterise at preview resolution
                ppix = page.get_pixmap(matrix=preview_matrix)
                rendered_img = Image.frombytes("RGB", (ppix.width, ppix.height), ppix.samples)
            preview_name = _save_preview(rendered_img, previews_dir, i)

        page_md = f"<!-- page {i} -->\n\n{page_md}"
        page_chunks.append(page_md)

        row = {"page": i, "source": source, "preview": preview_name}
        row.update(text_stats(page_md))
        if layout_counts is not None:
            row["image_count"] = layout_counts.get("image_count", 0)
            row["table_count"] = layout_counts.get("table_count", 0)
            row["formula_count"] = layout_counts.get("formula_count", 0)
        else:
            row["image_count"] = count_images(page_md)
            row["table_count"] = count_md_tables(page_md)
            row["formula_count"] = count_formulas(page_md)
        page_rows.append(row)

        if progress_callback:
            progress_callback(i - start + 1, end - start)

    markdown = "\n\n".join(page_chunks)
    return {"markdown": markdown, "pages": page_rows, "page_count": total}
