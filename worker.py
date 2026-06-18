#!/usr/bin/env python
"""Isolated conversion worker — runs in its own OS process, one per job.

Invoked as:  python worker.py <job_dir>

It reads <job_dir>/job.json, runs convert_pdf/convert_docx, and writes
progress.json, result.json (+ converted.md) on success, or error.json on a
caught failure. A hard crash (e.g. PP-StructureV3 segfault) simply kills this
process with no result/error file — the parent server detects that via the
non-zero exit code. Keeping conversion in a separate process is what stops a
segfault from taking down the web server.
"""

import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def write_json_atomic(path: Path, data: dict) -> None:
    """Write JSON to a temp file then atomically replace the target.

    Path.replace() maps to MoveFileEx with replace-existing on Windows, which
    is atomic for same-directory renames — so a polling reader never sees a
    half-written file.
    """
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python worker.py <job_dir>", file=sys.stderr)
        sys.exit(2)

    job_dir = Path(sys.argv[1]).resolve()
    progress_path = job_dir / "progress.json"

    # Test-only hook to exercise the crash-detection path without a real
    # segfault. Not wired into the UI.
    if os.environ.get("WORKER_FAKE_CRASH") == "1":
        os._exit(139)

    job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    images_dir = job_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    write_json_atomic(
        progress_path,
        {"status": "running", "done": 0, "total": 0, "page": None, "updated_at": _now()},
    )

    try:
        # Optional searchable-PDF output (PDF + image inputs): each page writes a
        # single-page PDF here; they're merged in order once conversion finishes.
        make_searchable = job.get("make_searchable", False)
        searchable_pages_dir = job_dir / "searchable_pages"

        def on_searchable(idx: int, pdf_bytes: bytes) -> None:
            searchable_pages_dir.mkdir(parents=True, exist_ok=True)
            (searchable_pages_dir / f"{idx:05d}.pdf").write_bytes(pdf_bytes)

        searchable_cb = on_searchable if make_searchable else None

        if job["file_type"] == "pdf":
            from converters.pdf_converter import convert_pdf

            file_bytes = (job_dir / "input.pdf").read_bytes()

            def on_progress(done: int, total: int) -> None:
                write_json_atomic(
                    progress_path,
                    {"status": "running", "done": done, "total": total, "updated_at": _now()},
                )

            # Live compare: persist each page the instant it finishes so the UI can
            # show "original vs converted" while the rest of the document is still
            # processing — not only at the end.
            pages_dir = job_dir / "pages"
            pages_dir.mkdir(parents=True, exist_ok=True)
            live_rows: list[dict] = []

            def on_page(page_index: int, page_md: str, row: dict) -> None:
                (pages_dir / f"{page_index}.md").write_text(page_md, encoding="utf-8")
                live_rows.append(
                    {
                        "page": row.get("page"),
                        "source": row.get("source"),
                        "preview": row.get("preview"),
                        "word_count": row.get("word_count", 0),
                    }
                )
                write_json_atomic(job_dir / "live.json", {"pages": live_rows})

            result = convert_pdf(
                file_bytes,
                images_dir,
                lang=job.get("lang", "ben+eng"),
                dpi=job.get("dpi", 300),
                use_layout=job.get("use_layout", False),
                start_page=job.get("start_page", 0),
                end_page=job.get("end_page"),
                progress_callback=on_progress,
                previews_dir=job_dir / "previews",
                page_callback=on_page,
                preprocess_scans=job.get("preprocess", True),
                searchable_callback=searchable_cb,
                conf_dir=job_dir / "conf",
            )
            rows = result["pages"]
            label_col = "page"
        elif job["file_type"] in {"png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff", "gif"}:
            from converters.image_converter import convert_image

            ftype = job["file_type"]
            file_bytes = (job_dir / f"input.{ftype}").read_bytes()

            # An image is one page; reuse the live/preview plumbing so the compare
            # view works exactly as it does for scanned PDF pages.
            pages_dir = job_dir / "pages"
            pages_dir.mkdir(parents=True, exist_ok=True)
            live_rows: list[dict] = []

            def on_page(page_index: int, page_md: str, row: dict) -> None:
                (pages_dir / f"{page_index}.md").write_text(page_md, encoding="utf-8")
                live_rows.append(
                    {
                        "page": row.get("page"),
                        "source": row.get("source"),
                        "preview": row.get("preview"),
                        "word_count": row.get("word_count", 0),
                    }
                )
                write_json_atomic(job_dir / "live.json", {"pages": live_rows})

            result = convert_image(
                file_bytes,
                images_dir,
                lang=job.get("lang", "ben+eng"),
                use_layout=job.get("use_layout", False),
                previews_dir=job_dir / "previews",
                page_callback=on_page,
                preprocess_scans=job.get("preprocess", True),
                searchable_callback=searchable_cb,
                conf_dir=job_dir / "conf",
            )
            rows = result["pages"]
            label_col = "page"
        elif job["file_type"] == "docx":
            from converters.docx_converter import convert_docx

            file_bytes = (job_dir / "input.docx").read_bytes()
            result = convert_docx(file_bytes, images_dir)
            rows = result["sections"]
            label_col = "label"
        else:  # csv / xls / xlsx — tabular files rendered as Markdown tables
            from converters.csv_excel_converter import convert_csv_excel

            ftype = job["file_type"]
            file_bytes = (job_dir / f"input.{ftype}").read_bytes()
            result = convert_csv_excel(file_bytes, ftype)
            rows = result["sections"]
            label_col = "label"

        markdown_out = result["markdown"]
        if job.get("gen_toc"):
            from converters.postprocess import build_toc

            markdown_out = build_toc(markdown_out)
        (job_dir / "converted.md").write_text(markdown_out, encoding="utf-8")

        # Merge per-page searchable PDFs (in page order) into one file.
        if make_searchable and searchable_pages_dir.exists():
            from converters.searchable import merge_to_file

            page_pdfs = sorted(searchable_pages_dir.glob("*.pdf"))
            if page_pdfs:
                merge_to_file(page_pdfs, job_dir / "searchable.pdf")

        meta = {k: v for k, v in result.items() if k != "markdown"}
        meta["label_col"] = label_col
        write_json_atomic(job_dir / "result.json", meta)
        write_json_atomic(
            progress_path,
            {"status": "done", "done": len(rows), "total": len(rows), "updated_at": _now()},
        )
    except Exception as exc:  # noqa: BLE001 — record any failure for the UI
        write_json_atomic(
            job_dir / "error.json",
            {"message": str(exc), "traceback": traceback.format_exc(), "updated_at": _now()},
        )
        write_json_atomic(
            progress_path,
            {"status": "error", "message": str(exc), "updated_at": _now()},
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
