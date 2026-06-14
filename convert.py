#!/usr/bin/env python
"""doc2md - convert scanned/digital PDFs and DOCX files to Markdown, locally.

No LLM / cloud APIs. Runs entirely offline using PyMuPDF, pymupdf4llm,
Tesseract OCR, mammoth/markdownify, and (optionally) PaddleOCR PP-StructureV3.

Usage:
    python convert.py chemistry-1.pdf -o output --lang ben+eng --pages 1-20
    python convert.py report.docx -o output
"""

import argparse
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn, TimeRemainingColumn
from rich.table import Table

from converters.docx_converter import convert_docx
from converters.pdf_converter import convert_pdf

console = Console()


def parse_page_range(spec: str | None, total_pages: int) -> tuple[int, int]:
    """Parse a 1-based page range like '1-20' or '5' into a 0-based (start, end) pair."""
    if not spec:
        return 0, total_pages
    spec = spec.strip()
    if "-" in spec:
        start_s, end_s = spec.split("-", 1)
        start = int(start_s) if start_s else 1
        end = int(end_s) if end_s else total_pages
    else:
        start = end = int(spec)
    start = max(1, start)
    end = min(total_pages, end)
    if start > end:
        raise ValueError(f"Invalid page range '{spec}'")
    return start - 1, end


def build_stats_table(rows: list[dict], label_col: str) -> Table:
    numeric_cols = [
        c
        for c in ["word_count", "char_count", "char_count_no_spaces", "image_count", "table_count", "formula_count"]
        if rows and c in rows[0]
    ]

    table = Table(title="Conversion stats", show_footer=True)
    table.add_column(label_col.title(), footer="TOTAL")
    if rows and "source" in rows[0]:
        table.add_column("Source", footer="")
    totals = {c: 0 for c in numeric_cols}
    for c in numeric_cols:
        table.add_column(c.replace("_", " ").title(), justify="right")

    for row in rows:
        cells = [str(row[label_col])]
        if "source" in row:
            cells.append(row["source"])
        for c in numeric_cols:
            cells.append(str(row[c]))
            totals[c] += row[c]
        table.add_row(*cells)

    footer_extra = [""] if rows and "source" in rows[0] else []
    table.columns[0].footer = "TOTAL"
    for i, c in enumerate(numeric_cols):
        col_index = 1 + len(footer_extra) + i
        table.columns[col_index].footer = str(totals[c])

    return table


def run_pdf(file_bytes: bytes, out_dir: Path, args) -> dict:
    import fitz

    doc = fitz.open(stream=file_bytes, filetype="pdf")
    total_pages = len(doc)
    doc.close()

    start, end = parse_page_range(args.pages, total_pages)
    console.print(f"[bold]PDF[/bold]: {total_pages} pages total, converting pages {start + 1}-{end}")

    images_dir = out_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    if args.use_layout:
        console.print(
            "[yellow]Warning:[/yellow] --use-layout (PP-StructureV3) is experimental and has been "
            "observed to crash (segfault) on some CPUs. If this process dies unexpectedly, "
            "re-run without --use-layout."
        )

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total} pages"),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Converting", total=end - start)

        def on_progress(done, _total):
            progress.update(task, completed=done)

        result = convert_pdf(
            file_bytes,
            images_dir,
            lang=args.lang,
            dpi=args.dpi,
            use_layout=args.use_layout,
            start_page=start,
            end_page=end,
            progress_callback=on_progress,
        )

    return result


def run_docx(file_bytes: bytes, out_dir: Path, args) -> dict:
    images_dir = out_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    console.print("[bold]DOCX[/bold]: converting...")
    return convert_docx(file_bytes, images_dir)


def main():
    parser = argparse.ArgumentParser(description="Convert a scanned/digital PDF or DOCX to Markdown.")
    parser.add_argument("input", help="Path to input .pdf or .docx file")
    parser.add_argument("-o", "--output", default=None, help="Output directory (default: <input>_md)")
    parser.add_argument("--lang", default="ben+eng", help="Tesseract OCR language(s), e.g. ben+eng, eng, ben")
    parser.add_argument("--dpi", type=int, default=300, help="Render DPI for scanned pages (default 300)")
    parser.add_argument(
        "--pages", default=None, help="Page range to convert, 1-based, e.g. '1-20' or '5' (PDF only)"
    )
    parser.add_argument(
        "--use-layout",
        action="store_true",
        help="Enable PP-StructureV3 layout analysis for scanned pages (experimental, may crash)",
    )
    args = parser.parse_args()

    in_path = Path(args.input)
    if not in_path.exists():
        console.print(f"[red]Error:[/red] file not found: {in_path}")
        sys.exit(1)

    out_dir = Path(args.output) if args.output else in_path.with_name(in_path.stem + "_md")
    out_dir.mkdir(parents=True, exist_ok=True)

    file_bytes = in_path.read_bytes()
    suffix = in_path.suffix.lower()

    start_time = time.time()
    if suffix == ".pdf":
        result = run_pdf(file_bytes, out_dir, args)
        rows, label_col = result["pages"], "page"
    elif suffix == ".docx":
        result = run_docx(file_bytes, out_dir, args)
        rows, label_col = result["sections"], "label"
    else:
        console.print(f"[red]Error:[/red] unsupported file type: {suffix} (expected .pdf or .docx)")
        sys.exit(1)
    elapsed = time.time() - start_time

    md_path = out_dir / "converted.md"
    md_path.write_text(result["markdown"], encoding="utf-8")

    console.print()
    console.print(build_stats_table(rows, label_col))
    console.print()
    console.print(f"[green]Done[/green] in {elapsed:.1f}s -> {md_path}")
    images_dir = out_dir / "images"
    image_files = list(images_dir.glob("*")) if images_dir.exists() else []
    if image_files:
        console.print(f"Extracted {len(image_files)} image(s) -> {images_dir}")


if __name__ == "__main__":
    main()
