"""Convert .docx files to Markdown via mammoth + markdownify, extracting images."""

import re
from pathlib import Path

import mammoth
from markdownify import markdownify as html_to_markdown

from converters.stats import count_formulas, count_images, count_md_tables, text_stats

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)


def convert_docx(file_bytes: bytes, images_dir: Path) -> dict:
    """Convert a .docx file to Markdown.

    Returns a dict with keys: markdown (str), sections (list of per-section stat dicts).
    Images referenced in the document are written to images_dir and linked
    as images/<name> in the markdown.
    """
    images_dir.mkdir(parents=True, exist_ok=True)
    image_counter = {"n": 0}

    def convert_image(image):
        image_counter["n"] += 1
        ext = (image.content_type or "image/png").split("/")[-1]
        if ext == "jpeg":
            ext = "jpg"
        name = f"docx_img_{image_counter['n']}.{ext}"
        with image.open() as src:
            data = src.read()
        (images_dir / name).write_bytes(data)
        return {"src": f"images/{name}"}

    image_handler = mammoth.images.img_element(convert_image)
    with _bytes_stream(file_bytes) as stream:
        result = mammoth.convert_to_html(stream, convert_image=image_handler)

    html = result.value
    markdown = html_to_markdown(html, heading_style="ATX").strip()

    sections = _split_sections(markdown)
    return {"markdown": markdown, "sections": sections}


def _bytes_stream(data: bytes):
    import io

    return io.BytesIO(data)


def _split_sections(markdown: str) -> list[dict]:
    """Split markdown into sections on top-level headings, with per-section stats."""
    headings = list(_HEADING_RE.finditer(markdown))
    sections = []

    if not headings:
        sections.append(_build_section_row("Document", markdown))
        return sections

    if headings[0].start() > 0:
        intro = markdown[: headings[0].start()].strip()
        if intro:
            sections.append(_build_section_row("Document", intro))

    for i, match in enumerate(headings):
        start = match.start()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(markdown)
        chunk = markdown[start:end].strip()
        title = match.group(2).strip()
        sections.append(_build_section_row(title or f"Section {i + 1}", chunk))

    return sections


def _build_section_row(label: str, markdown: str) -> dict:
    row = {"label": label, "source": "docx"}
    row.update(text_stats(markdown))
    row["image_count"] = count_images(markdown)
    row["table_count"] = count_md_tables(markdown)
    row["formula_count"] = count_formulas(markdown)
    return row
