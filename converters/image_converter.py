"""Convert a single image (PNG/JPG/WEBP/BMP/TIFF) to Markdown via OCR.

An image is treated as one scanned page: it reuses the exact OCR paths from
pdf_converter (plain Tesseract, or the layout pipeline with a Tesseract
fallback) and emits the same {markdown, pages} contract — including a downscaled
preview and the per-page callback — so the side-by-side compare view and the
live, during-conversion preview work just as they do for scanned PDFs.
"""

import io
import json
from pathlib import Path

import pytesseract
from PIL import Image, ImageOps

from converters import confidence, layout_ocr, preprocess, searchable, tesseract_config  # noqa: F401  (sets tesseract path)
from converters.pdf_converter import _save_preview
from converters.stats import count_formulas, count_images, count_md_tables, text_stats

# Common raster formats Pillow can open and Tesseract can OCR.
IMAGE_TYPES = {"png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff", "gif"}

# Tesseract rejects images beyond ~32767px on a side; keep well under that.
MAX_IMAGE_DIM = 8000


def _load_image(file_bytes: bytes) -> Image.Image:
    """Open image bytes as RGB, honour EXIF orientation, and cap the size."""
    img = Image.open(io.BytesIO(file_bytes))
    img = ImageOps.exif_transpose(img)  # rotate per EXIF so OCR reads upright
    img = img.convert("RGB")
    longest = max(img.size)
    if longest > MAX_IMAGE_DIM:
        scale = MAX_IMAGE_DIM / longest
        img = img.resize((int(img.width * scale), int(img.height * scale)))
    return img


def convert_image(
    file_bytes: bytes,
    images_dir: Path,
    lang: str = "ben+eng",
    use_layout: bool = True,
    previews_dir: Path | None = None,
    progress_callback=None,
    page_callback=None,
    preprocess_scans: bool = True,
    searchable_callback=None,
    conf_dir: Path | None = None,
) -> dict:
    """Convert a single image to Markdown.

    Returns a dict with keys: markdown (str), pages (list with one stat dict).
    Mirrors convert_pdf so the worker and the compare/live views need no special
    casing — the image is page 0.
    """
    images_dir.mkdir(parents=True, exist_ok=True)
    img = _load_image(file_bytes)

    # OCR on the enhanced image; the preview keeps the original so the compare
    # view shows what was actually uploaded.
    ocr_img = preprocess.enhance(img) if preprocess_scans else img

    layout_counts = None
    conf_info = None  # (mean, low, html) when whole-page OCR ran
    if use_layout:
        try:
            page_md, layout_counts = layout_ocr.process_page_image(ocr_img, lang, images_dir, 0)
        except Exception:
            page_md, c_mean, c_low, c_html = confidence.ocr_with_confidence(ocr_img, lang)
            conf_info = (c_mean, c_low, c_html)
            layout_counts = None
    else:
        page_md, c_mean, c_low, c_html = confidence.ocr_with_confidence(ocr_img, lang)
        conf_info = (c_mean, c_low, c_html)

    preview_name = None
    if previews_dir is not None:
        preview_name = _save_preview(img, previews_dir, 0)

    page_md = f"<!-- page 0 -->\n\n{page_md}"

    row = {"page": 0, "source": "ocr", "preview": preview_name}
    row.update(text_stats(page_md))
    if layout_counts is not None:
        row["image_count"] = layout_counts.get("image_count", 0)
        row["table_count"] = layout_counts.get("table_count", 0)
        row["formula_count"] = layout_counts.get("formula_count", 0)
    else:
        row["image_count"] = count_images(page_md)
        row["table_count"] = count_md_tables(page_md)
        row["formula_count"] = count_formulas(page_md)

    if conf_info is not None:
        c_mean, c_low, c_html = conf_info
        row["mean_conf"] = c_mean
        row["low_conf_count"] = c_low
        if conf_dir is not None:
            conf_dir.mkdir(parents=True, exist_ok=True)
            (conf_dir / "0.json").write_text(
                json.dumps({"mean": c_mean, "low": c_low, "html": c_html}, ensure_ascii=False),
                encoding="utf-8",
            )

    if searchable_callback:
        # Embed the same (enhanced) image we OCR'd so the text layer aligns.
        try:
            searchable_callback(0, searchable.page_pdf_from_image(ocr_img, lang))
        except Exception:
            pass
    if page_callback:
        page_callback(0, page_md, row)
    if progress_callback:
        progress_callback(1, 1)

    return {"markdown": page_md, "pages": [row], "page_count": 1}
