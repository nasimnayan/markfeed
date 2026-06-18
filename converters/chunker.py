"""Build RAG-ready chunked JSON from a finished job.

One chunk per natural unit — PDF/image: a page; docx/csv/excel: a heading/sheet
section — each carrying its source location, per-chunk stats, and image links. No
LLM: assembled purely from the markdown + metadata the converters already produced,
so it works for any completed job (and is generated lazily on request).

This module also owns the canonical page-marker splitter used by the web layer.
"""

import json
import re
from pathlib import Path

from converters.stats import count_images, count_md_tables, text_stats

PAGE_SPLIT_RE = re.compile(r"<!--\s*page\s+(\d+)\s*-->")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def split_pages(md_text: str) -> dict[int, str]:
    """Split combined markdown back into per-page chunks on the page markers."""
    parts = PAGE_SPLIT_RE.split(md_text)
    pages: dict[int, str] = {}
    for k in range(1, len(parts) - 1, 2):
        pages[int(parts[k])] = parts[k + 1].strip()
    return pages


def split_sections(md_text: str) -> list[tuple[str, str]]:
    """Split markdown into (label, text) sections on top-level headings.

    Mirrors docx_converter._split_sections so docx/csv chunks line up with how the
    document is actually structured; flat text with no headings is one section.
    """
    headings = list(_HEADING_RE.finditer(md_text))
    if not headings:
        return [("Document", md_text.strip())]

    sections: list[tuple[str, str]] = []
    if headings[0].start() > 0:
        intro = md_text[: headings[0].start()].strip()
        if intro:
            sections.append(("Document", intro))
    for i, match in enumerate(headings):
        start = match.start()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(md_text)
        title = match.group(2).strip() or f"Section {i + 1}"
        sections.append((title, md_text[start:end].strip()))
    return sections


def _windows(text: str, size: int, overlap: int) -> list[str]:
    """Split text into overlapping char windows (sub-chunking; off when size<=0)."""
    if size <= 0 or len(text) <= size:
        return [text]
    step = max(1, size - overlap)
    return [text[i : i + size] for i in range(0, len(text), step)]


def _chunk(chunk_id: int, source: dict, text: str) -> dict:
    stats = text_stats(text)
    return {
        "chunk_id": chunk_id,
        **source,  # source_page (1-based) or source_section
        "text": text,
        "word_count": stats["word_count"],
        "char_count": stats["char_count"],
        "image_count": count_images(text),
        "table_count": count_md_tables(text),
        "images": _IMAGE_RE.findall(text),
    }


def build_chunks(job_dir: Path, *, chunk_chars: int = 0, overlap: int = 0) -> dict:
    """Assemble {document, chunks} for a completed job.

    chunk_chars/overlap enable optional fixed-size sub-chunking (default off → one
    chunk per page/section, the reviewed v1 behaviour).
    """
    job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    meta = json.loads((job_dir / "result.json").read_text(encoding="utf-8"))
    md = (job_dir / "converted.md").read_text(encoding="utf-8")
    label_col = meta.get("label_col", "page")

    chunks: list[dict] = []
    if label_col == "page":  # PDF / image — split on page markers, 1-based pages
        unit = "page"
        pages = split_pages(md)
        for page_index in sorted(pages):
            text = pages[page_index].strip()
            if not text:
                continue
            for win in _windows(text, chunk_chars, overlap):
                chunks.append(_chunk(len(chunks) + 1, {"source_page": page_index + 1}, win))
    else:  # docx / csv / excel — heading/sheet sections
        unit = "section"
        for label, text in split_sections(md):
            if not text:
                continue
            for win in _windows(text, chunk_chars, overlap):
                chunks.append(_chunk(len(chunks) + 1, {"source_section": label}, win))

    document = {
        "filename": job.get("filename"),
        "file_type": job.get("file_type"),
        "language": job.get("lang"),
        "created_at": job.get("created_at"),
        "unit": unit,
        "chunk_count": len(chunks),
        # Provenance + future tiering hook: record which capabilities produced this.
        "features": {
            "preprocess": job.get("preprocess"),
            "use_layout": job.get("use_layout"),
            "make_searchable": job.get("make_searchable"),
            "gen_toc": job.get("gen_toc"),
            "preset": job.get("preset"),
        },
    }
    return {"document": document, "chunks": chunks}
