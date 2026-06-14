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
        if job["file_type"] == "pdf":
            from converters.pdf_converter import convert_pdf

            file_bytes = (job_dir / "input.pdf").read_bytes()

            def on_progress(done: int, total: int) -> None:
                write_json_atomic(
                    progress_path,
                    {"status": "running", "done": done, "total": total, "updated_at": _now()},
                )

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
            )
            rows = result["pages"]
            label_col = "page"
        else:
            from converters.docx_converter import convert_docx

            file_bytes = (job_dir / "input.docx").read_bytes()
            result = convert_docx(file_bytes, images_dir)
            rows = result["sections"]
            label_col = "label"

        (job_dir / "converted.md").write_text(result["markdown"], encoding="utf-8")

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
