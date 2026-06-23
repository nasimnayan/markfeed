"""Convert PDF files (digital or scanned) to Markdown with per-page stats."""

import io
import json
import re
from pathlib import Path

import fitz  # PyMuPDF
import pymupdf4llm
import pytesseract
from PIL import Image

from converters import confidence, layout_ocr, preprocess, searchable, tesseract_config  # noqa: F401  (sets tesseract path)
from converters.stats import count_formulas, count_images, count_md_tables, text_stats

# pymupdf4llm wraps an image-with-text-layer region as an "omitted picture" plus a
# flat "picture text" dump of everything inside it. When that region is actually a
# data table, find_tables() reconstructs it correctly -- swap the dump for that.
_PICTURE_TEXT_RE = re.compile(
    r"\*\*==> picture \[[^\]]*\] intentionally omitted <==\*\*\n\n"
    r"\*\*----- Start of picture text -----\*\*<br>\n"
    r".*?"
    r"\*\*----- End of picture text -----\*\*<br>\n?",
    re.DOTALL,
)

# A table bbox covering almost the whole page is usually a false positive from the
# page border, not a real table.
_TABLE_AREA_RATIO_MAX = 0.95


def _inject_missing_tables(page_md: str, page: fitz.Page) -> str:
    """Replace OCR'd "picture text" dumps with proper Markdown tables where possible."""
    if count_md_tables(page_md) > 0 or "----- Start of picture text -----" not in page_md:
        return page_md

    page_area = page.rect.width * page.rect.height
    tables = [
        t
        for t in page.find_tables().tables
        if t.row_count >= 2
        and t.col_count >= 2
        and (t.bbox[2] - t.bbox[0]) * (t.bbox[3] - t.bbox[1]) / page_area <= _TABLE_AREA_RATIO_MAX
    ]
    if not tables:
        return page_md

    table_md = "\n\n".join(t.to_markdown().strip() for t in tables)
    remainder = _PICTURE_TEXT_RE.sub("", page_md).strip()
    return f"{remainder}\n\n{table_md}" if remainder else table_md

DIGITAL_TEXT_THRESHOLD = 20  # min chars of extractable text to treat a page as "digital"

# Some "scanned" pages are exported as a single oversized image covering the whole
# page with only a tiny watermark as real text (e.g. "www.example.com" repeated a
# few times). get_text() then exceeds DIGITAL_TEXT_THRESHOLD even though the real
# content needs OCR. Detect that case and OCR the embedded image directly: only
# check pages whose text is still small (likely just a watermark), and only treat
# an image as the page content if it covers almost the entire page.
DOMINANT_IMAGE_MAX_TEXT = 200
DOMINANT_IMAGE_AREA_THRESHOLD = 0.9


def _dominant_page_image(doc: fitz.Document, page: fitz.Page) -> Image.Image | None:
    """Return the embedded image as a PIL Image if it covers nearly the whole page."""
    page_area = page.rect.width * page.rect.height
    if not page_area:
        return None
    for info in page.get_image_info(xrefs=True):
        bbox = fitz.Rect(info["bbox"]) & page.rect
        if (bbox.width * bbox.height) / page_area >= DOMINANT_IMAGE_AREA_THRESHOLD:
            data = doc.extract_image(info["xref"])["image"]
            return Image.open(io.BytesIO(data)).convert("RGB")
    return None


# Tesseract rejects images with a dimension beyond ~32767px ("Image too large").
# Some pages (e.g. very tall single-image scans) render past that at high DPI, so
# cap the render size and accept lower resolution rather than crashing the job.
MAX_RENDER_DIM = 8000


def _capped_matrix(rect: fitz.Rect, matrix: fitz.Matrix) -> fitz.Matrix:
    """Shrink the render matrix so neither output dimension exceeds MAX_RENDER_DIM."""
    transformed = rect * matrix
    longest = max(transformed.width, transformed.height)
    if longest <= MAX_RENDER_DIM:
        return matrix
    scale = MAX_RENDER_DIM / longest
    return matrix * fitz.Matrix(scale, scale)


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
    page_callback=None,
    preprocess_scans: bool = True,
    searchable_callback=None,
    conf_dir: Path | None = None,
    done_pages: set | None = None,
    prior_pages: dict | None = None,
    force_plain_pages: set | None = None,
    skip_pages: set | None = None,
    before_page_callback=None,
) -> dict:
    """Convert a PDF to Markdown.

    Returns a dict with keys: markdown (str), pages (list of per-page stat dicts).
    When previews_dir is given, a downscaled JPEG of each page is saved there and
    its filename recorded on the page row (for the side-by-side compare view).
    When page_callback is given it is called as page_callback(page_index, page_md,
    row) the moment each page finishes — this powers the live, during-conversion
    compare view (the caller persists the chunk + row so the UI can show it before
    the whole document is done).

    Resume support (for long extraction runs that may crash mid-document):
    - done_pages / prior_pages: page indices already converted in a previous run,
      with their saved {"md", "row"} so they are re-emitted in order without
      re-OCR (keeps the assembled markdown + stats complete on a resumed run).
    - force_plain_pages: indices to OCR with plain Tesseract even if use_layout is
      on (the layout model is what segfaults — this is the poison-page guard).
    - skip_pages: indices to emit as a "could not process" placeholder (used when a
      page crashed even in plain mode, so a resume never loops on it forever).
    - before_page_callback(i): called just before a page is *actually processed*
      (not for done/skip pages) so the caller can checkpoint which page is in
      flight, enabling poison-page detection after a hard crash.
    """
    done_pages = done_pages or set()
    prior_pages = prior_pages or {}
    force_plain_pages = force_plain_pages or set()
    skip_pages = skip_pages or set()

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
        # Resume fast path: a page already converted in an earlier run is re-emitted
        # from its saved markdown + row (no OCR), keeping order and stats intact.
        if i in done_pages and i in prior_pages:
            page_md = prior_pages[i]["md"]
            row = prior_pages[i]["row"]
            page_chunks.append(page_md)
            page_rows.append(row)
            if page_callback:
                page_callback(i, page_md, row)
            if progress_callback:
                progress_callback(i - start + 1, end - start)
            continue

        # A page that crashed the worker even in plain mode: emit a visible
        # placeholder so the document stays complete and a resume never re-attempts it.
        if i in skip_pages:
            page_md = f"<!-- page {i} -->\n\n*[Page {i + 1} could not be processed and was skipped.]*"
            page_chunks.append(page_md)
            row = {"page": i, "source": "skipped", "preview": None}
            row.update(text_stats(page_md))
            row["image_count"] = 0
            row["table_count"] = 0
            row["formula_count"] = 0
            page_rows.append(row)
            if page_callback:
                page_callback(i, page_md, row)
            if progress_callback:
                progress_callback(i - start + 1, end - start)
            continue

        # Checkpoint the page about to be processed so a hard crash here is
        # attributable to this exact page on the next resume (poison-page guard).
        if before_page_callback:
            before_page_callback(i)

        page = doc[i]
        text = page.get_text().strip()
        layout_counts = None
        conf_info = None  # (mean, low, html) when whole-page OCR ran
        rendered_img = None  # full-res render, reused for the preview when present

        dominant_img = None
        if len(text) <= DOMINANT_IMAGE_MAX_TEXT:
            dominant_img = _dominant_page_image(doc, page)

        if len(text) > DIGITAL_TEXT_THRESHOLD and dominant_img is None:
            page_md = pymupdf4llm.to_markdown(
                doc, pages=[i], write_images=True, image_path=str(images_dir), use_ocr=False
            ).strip()
            page_md = _relativize_image_paths(page_md, images_dir)
            page_md = _inject_missing_tables(page_md, page)
            source = "digital"
            if searchable_callback:
                # Digital page already has real text — copy it as-is.
                try:
                    searchable_callback(i, searchable.page_pdf_from_pdf_page(doc, i))
                except Exception:
                    pass
        else:
            if dominant_img is not None:
                rendered_img = dominant_img
            else:
                pix = page.get_pixmap(matrix=_capped_matrix(page.rect, matrix))
                rendered_img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

            # OCR on the enhanced image; the preview keeps the original render so
            # the compare view shows what was actually scanned.
            ocr_img = preprocess.enhance(rendered_img) if preprocess_scans else rendered_img

            if use_layout and i not in force_plain_pages:
                try:
                    page_md, layout_counts = layout_ocr.process_page_image(
                        ocr_img, lang, images_dir, i
                    )
                except Exception:
                    page_md, c_mean, c_low, c_html = confidence.ocr_with_confidence(ocr_img, lang)
                    conf_info = (c_mean, c_low, c_html)
                    layout_counts = None
            else:
                page_md, c_mean, c_low, c_html = confidence.ocr_with_confidence(ocr_img, lang)
                conf_info = (c_mean, c_low, c_html)
                layout_counts = None

            source = "ocr"
            if searchable_callback:
                # Embed the same (enhanced) image we OCR'd so the hidden text layer
                # aligns with what the reader sees.
                try:
                    searchable_callback(i, searchable.page_pdf_from_image(ocr_img, lang))
                except Exception:
                    pass

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

        if conf_info is not None:
            c_mean, c_low, c_html = conf_info
            row["mean_conf"] = c_mean
            row["low_conf_count"] = c_low
            if conf_dir is not None:
                conf_dir.mkdir(parents=True, exist_ok=True)
                (conf_dir / f"{i}.json").write_text(
                    json.dumps({"mean": c_mean, "low": c_low, "html": c_html}, ensure_ascii=False),
                    encoding="utf-8",
                )
        page_rows.append(row)

        if page_callback:
            page_callback(i, page_md, row)
        if progress_callback:
            progress_callback(i - start + 1, end - start)

    markdown = "\n\n".join(page_chunks)
    return {"markdown": markdown, "pages": page_rows, "page_count": total}
