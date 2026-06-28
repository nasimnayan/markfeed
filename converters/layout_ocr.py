"""Layout-aware extraction for scanned PDF pages.

Replaces the crash-prone PP-StructureV3 pipeline with a hybrid of stable parts:
  * PaddleOCR's standalone **LayoutDetection** (PP-DocLayout) finds regions and
    their reading order  — proven stable on this machine (the full PP-StructureV3
    orchestration is what segfaults).
  * **Tesseract** reads text/title/formula regions (good Bengali support).
  * **img2table** (OpenCV + Tesseract) turns table regions into Markdown tables.
  * Figure/chart regions are cropped and saved as embedded images.

process_page_image() raises on hard failure so pdf_converter can fall back to
plain whole-page OCR for that page.
"""

import io
from pathlib import Path

import pytesseract
from PIL import Image

from converters import tesseract_config  # noqa: F401  (sets tesseract cmd + PATH)
from converters.confidence import LOW_CONF  # shared low-confidence threshold (60)

# Region label groups produced by PP-DocLayout_plus-L.
DOC_TITLE_LABELS = {"doc_title"}
TITLE_LABELS = {
    "paragraph_title", "figure_title", "table_title", "chart_title", "formula_caption",
}
FIGURE_LABELS = {"image", "figure", "chart", "seal"}
TABLE_LABELS = {"table"}
# Formulas are OCR'd inline as text (this book is formula-dense; cropping each to
# an image file would produce dozens of fragments per page).
FORMULA_LABELS = {"formula", "formula_number"}
# Everything else textual.
TEXT_LABELS = {
    "text", "content", "abstract", "reference", "reference_content", "footnote",
    "header", "footer", "number", "algorithm", "aside_text", "list",
}

_LAYOUT_THRESHOLD = 0.3  # default (0.5) misses body text on these scans

_layout_model = None
_table_ocr = {}  # lang -> TesseractOCR


def _get_layout_model():
    global _layout_model
    if _layout_model is None:
        from paddleocr import LayoutDetection

        _layout_model = LayoutDetection(
            model_name="PP-DocLayout_plus-L", enable_mkldnn=False, cpu_threads=1
        )
    return _layout_model


def _get_table_ocr(lang: str):
    if lang not in _table_ocr:
        from img2table.ocr import TesseractOCR

        _table_ocr[lang] = TesseractOCR(n_threads=1, lang=lang)
    return _table_ocr[lang]


def process_page_image(
    img: Image.Image,
    lang: str,
    images_dir: Path,
    page_index: int,
    collect_conf: bool = False,
):
    """Run layout-aware extraction on a rendered page.

    Returns ``(markdown, counts)`` by default. When ``collect_conf=True`` returns
    ``(markdown, counts, conf)`` where ``conf`` is ``(mean, low_count, html)`` or
    ``None`` when the page has no OCR'd text regions. The mean is **word-weighted**
    across all text/title/formula regions (raw per-word confidences are pooled and
    averaged once), and is a **partial-page** measure — it excludes img2table tables
    and cropped figures, which carry no Tesseract text confidence. The default-off
    flag keeps the legacy 2-tuple contract for other callers (image_converter,
    benchmark) unchanged.
    """
    import numpy as np

    img = img.convert("RGB")
    model = _get_layout_model()
    res = list(model.predict(np.array(img), threshold=_LAYOUT_THRESHOLD))[0]
    data = res.json["res"] if hasattr(res, "json") else res["res"]
    boxes = _dedup(data.get("boxes", []))
    boxes = _reading_order(boxes)

    counts = {"table_count": 0, "image_count": 0, "formula_count": 0}
    md_parts = []
    page_confs: list[float] = []  # pooled per-word confidences from all _ocr regions
    fig_n = 0

    for b in boxes:
        label = b.get("label", "text")
        crop = _crop(img, b.get("coordinate"))
        if crop is None:
            continue

        if label in TABLE_LABELS:
            table_md = _table_to_markdown(crop, lang) or _ocr_table_grid(crop, lang)
            if table_md:
                md_parts.append(table_md)
                counts["table_count"] += 1
            else:  # not a real grid -> fall back to plain text
                text, confs = _ocr(crop, lang)
                if text:
                    md_parts.append(text)
                    page_confs.extend(confs)
        elif label in FIGURE_LABELS:
            fig_n += 1
            fname = f"page_{page_index:04d}_fig_{fig_n}.png"
            crop.save(images_dir / fname)
            md_parts.append(f"![](images/{fname})")
            counts["image_count"] += 1
        elif label in DOC_TITLE_LABELS:
            text, confs = _ocr(crop, lang)
            if text:
                md_parts.append(f"# {text}")
                page_confs.extend(confs)
        elif label in TITLE_LABELS:
            text, confs = _ocr(crop, lang)
            if text:
                md_parts.append(f"## {text}")
                page_confs.extend(confs)
        else:  # text + formula labels -> inline text
            text, confs = _ocr(crop, lang)
            if text:
                md_parts.append(text)
                page_confs.extend(confs)
                if label in FORMULA_LABELS:
                    counts["formula_count"] += 1

    markdown = "\n\n".join(md_parts)
    if not collect_conf:
        return markdown, counts
    if page_confs:
        mean = round(sum(page_confs) / len(page_confs), 1)
        low = sum(1 for c in page_confs if c < LOW_CONF)
        conf = (mean, low, "")  # html highlight not built for hybrid regions yet
    else:
        conf = None
    return markdown, counts, conf


def _ocr(crop: Image.Image, lang: str) -> tuple[str, list[float]]:
    """OCR a text region; return (text, per-word confidence values).

    Uses ``image_to_data`` (the same engine pass as ``image_to_string``) so the
    confidences come for free in one pass. Text is rebuilt line-by-line and the
    confidences are filtered exactly as confidence.py does for plain OCR: skip
    empty words and skip Tesseract's -1 non-text sentinel. A region with no valid
    words returns ("", []) and so contributes nothing to the page mean.
    """
    data = pytesseract.image_to_data(crop, lang=lang, output_type=pytesseract.Output.DICT)
    lines: dict[tuple, list[str]] = {}
    order: list[tuple] = []
    confs: list[float] = []
    for i in range(len(data["text"])):
        word = data["text"][i]
        if not word or not word.strip():
            continue
        conf = float(data["conf"][i])
        if conf < 0:  # -1 marks non-text layout boxes
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        if key not in lines:
            lines[key] = []
            order.append(key)
        lines[key].append(word)
        confs.append(conf)
    text = "\n".join(" ".join(lines[k]) for k in order).strip()
    return text, confs


def _crop(img: Image.Image, bbox) -> Image.Image | None:
    if not bbox or len(bbox) != 4:
        return None
    x1, y1, x2, y2 = (int(round(v)) for v in bbox)
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(img.width, x2), min(img.height, y2)
    if x2 - x1 < 4 or y2 - y1 < 4:
        return None
    return img.crop((x1, y1, x2, y2))


def _table_to_markdown(crop: Image.Image, lang: str) -> str | None:
    """Extract a table from a cropped region via img2table; None if no grid found."""
    try:
        from img2table.document import Image as I2TImage

        buf = io.BytesIO()
        crop.save(buf, format="PNG")
        doc = I2TImage(src=buf.getvalue())
        tables = doc.extract_tables(ocr=_get_table_ocr(lang), borderless_tables=True)
        if not tables:
            return None
        df = tables[0].df
        if df is None or df.empty:
            return None
        return df.fillna("").astype(str).to_markdown(index=False)
    except Exception:
        return None


def _ocr_table_grid(crop: Image.Image, lang: str) -> str | None:
    """Reconstruct a markdown table from word bounding boxes.

    Fallback for tables img2table can't parse (faint/missing grid lines):
    values are still column-aligned in the scan, so cluster word positions
    into rows and columns and rebuild the grid from that.
    """
    data = pytesseract.image_to_data(crop, lang=lang, output_type=pytesseract.Output.DICT)
    words = [
        {"text": data["text"][i].strip(), "x": data["left"][i], "y": data["top"][i], "h": data["height"][i], "w": data["width"][i]}
        for i in range(len(data["text"]))
        if data["text"][i].strip()
    ]
    if len(words) < 4:
        return None

    # group into rows by vertical position
    words.sort(key=lambda w: w["y"])
    avg_h = sum(w["h"] for w in words) / len(words)
    row_gap = avg_h * 0.6
    rows = [[words[0]]]
    for w in words[1:]:
        if w["y"] - rows[-1][-1]["y"] > row_gap:
            rows.append([w])
        else:
            rows[-1].append(w)
    for r in rows:
        r.sort(key=lambda w: w["x"])
    if len(rows) < 2:
        return None

    # cluster word x-starts across all rows into column anchors
    xs = sorted(w["x"] for row in rows for w in row)
    avg_w = sum(w["w"] for row in rows for w in row) / len(xs)
    col_gap = avg_w * 1.5
    clusters = [[xs[0]]]
    for x in xs[1:]:
        if x - clusters[-1][-1] > col_gap:
            clusters.append([x])
        else:
            clusters[-1].append(x)
    columns = [sum(c) / len(c) for c in clusters]
    if len(columns) < 2:
        return None

    # assign each word to its nearest column and build the grid
    grid = []
    for row in rows:
        cells = [""] * len(columns)
        for w in row:
            idx = min(range(len(columns)), key=lambda i: abs(columns[i] - w["x"]))
            cells[idx] = (cells[idx] + " " + w["text"]).strip()
        grid.append([_escape_cell(c) for c in cells])

    lines = ["| " + " | ".join(grid[0]) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for row in grid[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _escape_cell(text: str) -> str:
    return text.replace("|", "\\|")


def _iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter == 0:
        return 0.0
    area_a = (ax2 - ax1) * (ay2 - ay1)
    area_b = (bx2 - bx1) * (by2 - by1)
    return inter / float(area_a + area_b - inter)


def _dedup(boxes: list[dict], iou_thresh: float = 0.6) -> list[dict]:
    """Drop overlapping detections, keeping the higher-scoring box."""
    kept: list[dict] = []
    for b in sorted(boxes, key=lambda x: x.get("score", 0), reverse=True):
        coord = b.get("coordinate")
        if not coord or len(coord) != 4:
            continue
        if any(_iou(coord, k["coordinate"]) > iou_thresh for k in kept):
            continue
        kept.append(b)
    return kept


def _reading_order(boxes: list[dict]) -> list[dict]:
    """Top-to-bottom, then left-to-right. A small vertical band keeps items on the
    same line ordered left-to-right (this book is single-column)."""
    if not boxes:
        return boxes
    heights = [b["coordinate"][3] - b["coordinate"][1] for b in boxes]
    band = max(8.0, (sum(heights) / len(heights)) * 0.5)
    return sorted(boxes, key=lambda b: (round(b["coordinate"][1] / band), b["coordinate"][0]))
