"""OCR with per-word confidence (plain-OCR pages).

Uses Tesseract's `image_to_data` — same OCR pass as `image_to_string`, just richer
output — so confidence comes essentially for free. Returns the reconstructed text
plus a mean confidence, a low-confidence word count, and a highlighted HTML version
(low-confidence words wrapped) that the verify view can show so a human knows exactly
where to check.

Only applies to whole-page (plain) OCR; layout mode does its own region OCR.
"""

import html as _html

import pytesseract
from PIL import Image

from converters import tesseract_config  # noqa: F401  (sets tesseract cmd + PATH)

# Words below this Tesseract confidence (0–100) are flagged for review.
LOW_CONF = 60


def ocr_with_confidence(img: Image.Image, lang: str) -> tuple[str, float | None, int, str]:
    """Return (text, mean_confidence, low_confidence_count, highlighted_html)."""
    data = pytesseract.image_to_data(img, lang=lang, output_type=pytesseract.Output.DICT)
    n = len(data["text"])

    paras: list[tuple] = []          # preserve paragraph order
    pmap: dict[tuple, dict] = {}     # (block,par) -> {line_num: [(word, conf)]}
    confs: list[float] = []

    for i in range(n):
        word = data["text"][i]
        if not word or not word.strip():
            continue
        conf = float(data["conf"][i])
        if conf < 0:  # -1 marks non-text layout boxes
            continue
        pkey = (data["block_num"][i], data["par_num"][i])
        if pkey not in pmap:
            pmap[pkey] = {}
            paras.append(pkey)
        pmap[pkey].setdefault(data["line_num"][i], []).append((word, conf))
        confs.append(conf)

    text_paras: list[str] = []
    html_paras: list[str] = []
    for pkey in paras:
        lines = pmap[pkey]
        line_texts: list[str] = []
        line_htmls: list[str] = []
        for lkey in sorted(lines):
            words = lines[lkey]
            line_texts.append(" ".join(w for w, _ in words))
            spans = []
            for w, c in words:
                esc = _html.escape(w)
                if c < LOW_CONF:
                    spans.append(f'<span class="lc" title="{c:.0f}% confidence">{esc}</span>')
                else:
                    spans.append(esc)
            line_htmls.append(" ".join(spans))
        text_paras.append("\n".join(line_texts))
        html_paras.append("<p>" + "<br>".join(line_htmls) + "</p>")

    text = "\n\n".join(text_paras)
    mean = round(sum(confs) / len(confs), 1) if confs else None
    low = sum(1 for c in confs if c < LOW_CONF)
    return text, mean, low, "".join(html_paras)
