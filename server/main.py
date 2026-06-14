"""FastAPI web UI for the offline document-to-markdown converter.

Conversion runs in isolated subprocesses (see server/jobs.py + worker.py) so a
native crash in the layout-OCR pipeline can never take down this server.
"""

import io
import re
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

import markdown as md_lib
from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from server.jobs import JobManager

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = Path(__file__).resolve().parent / "static"

job_manager = JobManager()

NUMERIC_COLS = [
    "word_count",
    "char_count",
    "char_count_no_spaces",
    "image_count",
    "table_count",
    "formula_count",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio

    task = asyncio.create_task(job_manager.worker_loop())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="Folio", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.post("/api/jobs")
async def create_job(
    file: UploadFile,
    lang: str = Form("ben+eng"),
    dpi: int = Form(300),
    use_layout: bool = Form(False),
    start_page: int | None = Form(None),
    end_page: int | None = Form(None),
):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".pdf", ".docx"):
        raise HTTPException(400, "Only .pdf and .docx files are supported")
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(400, "Uploaded file is empty")

    start = (start_page - 1) if start_page and start_page > 0 else 0
    end = end_page

    # Diagram + table extraction is heavy: clamp the range to a smart per-run cap.
    if use_layout and suffix == ".pdf":
        import fitz

        from converters.limits import extraction_page_cap

        total = fitz.open(stream=file_bytes, filetype="pdf").page_count
        cap = extraction_page_cap(total)
        if end is None:
            end = total
        if end - start > cap:
            end = start + cap

    job_id = job_manager.create_job(
        file.filename or f"upload{suffix}",
        file_bytes,
        {
            "file_type": "pdf" if suffix == ".pdf" else "docx",
            "lang": lang,
            "dpi": dpi,
            "use_layout": use_layout,
            "start_page": start,
            "end_page": end,
        },
    )
    return {"job_id": job_id}


@app.post("/api/pdf-info")
async def pdf_info(file: UploadFile):
    """Return page count + the extraction-mode cap so the UI can guide the user."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix != ".pdf":
        return {"page_count": None, "extraction_cap": None}
    import fitz

    from converters.limits import extraction_page_cap

    file_bytes = await file.read()
    total = fitz.open(stream=file_bytes, filetype="pdf").page_count
    return {"page_count": total, "extraction_cap": extraction_page_cap(total)}


@app.get("/api/jobs")
def list_jobs():
    return job_manager.list_jobs()


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    status = job_manager.get_status(job_id)
    if status is None:
        raise HTTPException(404, "Job not found")
    return status


def _require_done(job_id: str) -> Path:
    job_dir = job_manager._job_dir(job_id)
    if not (job_dir / "converted.md").exists():
        raise HTTPException(404, "Result not ready")
    return job_dir


@app.get("/api/jobs/{job_id}/markdown", response_class=PlainTextResponse)
def job_markdown(job_id: str):
    job_dir = _require_done(job_id)
    return (job_dir / "converted.md").read_text(encoding="utf-8")


@app.get("/api/jobs/{job_id}/preview", response_class=HTMLResponse)
def job_preview(job_id: str):
    job_dir = _require_done(job_id)
    text = (job_dir / "converted.md").read_text(encoding="utf-8")
    html = md_lib.markdown(text, extensions=["tables", "fenced_code", "sane_lists", "nl2br"])
    # Point relative image links at this job's image route.
    html = re.sub(
        r'(<img[^>]*\bsrc=")images/',
        rf'\1/api/jobs/{job_id}/images/',
        html,
    )
    return html


@app.get("/api/jobs/{job_id}/stats")
def job_stats(job_id: str):
    job_dir = _require_done(job_id)
    import json

    meta = json.loads((job_dir / "result.json").read_text(encoding="utf-8"))
    label_col = meta.get("label_col", "page")
    rows = meta.get("pages") or meta.get("sections") or []
    totals = {c: 0 for c in NUMERIC_COLS}
    for row in rows:
        for c in NUMERIC_COLS:
            totals[c] += row.get(c, 0) or 0
    return {"label_col": label_col, "rows": rows, "totals": totals}


@app.get("/api/jobs/{job_id}/images/{name}")
def job_image(job_id: str, name: str):
    safe = Path(name).name  # path-traversal guard
    img_path = job_manager._job_dir(job_id) / "images" / safe
    if not img_path.exists():
        raise HTTPException(404, "Image not found")
    return FileResponse(str(img_path))


@app.get("/api/jobs/{job_id}/previews/{name}")
def job_preview_image(job_id: str, name: str):
    safe = Path(name).name  # path-traversal guard
    img_path = job_manager._job_dir(job_id) / "previews" / safe
    if not img_path.exists():
        raise HTTPException(404, "Preview not found")
    return FileResponse(str(img_path))


_PAGE_SPLIT_RE = re.compile(r"<!--\s*page\s+(\d+)\s*-->")


def _split_pages(md_text: str) -> dict[int, str]:
    """Split combined markdown back into per-page chunks on the page markers."""
    parts = _PAGE_SPLIT_RE.split(md_text)
    pages: dict[int, str] = {}
    for k in range(1, len(parts) - 1, 2):
        pages[int(parts[k])] = parts[k + 1].strip()
    return pages


@app.get("/api/jobs/{job_id}/compare")
def job_compare(job_id: str):
    """Lightweight page list (no markdown) powering the side-by-side viewer."""
    job_dir = _require_done(job_id)
    import json

    meta = json.loads((job_dir / "result.json").read_text(encoding="utf-8"))
    rows = meta.get("pages") or []
    pages = [
        {
            "page": r.get("page"),
            "source": r.get("source"),
            "preview": r.get("preview"),
            "word_count": r.get("word_count", 0),
        }
        for r in rows
        if r.get("preview")
    ]
    return {"pages": pages}


@app.get("/api/jobs/{job_id}/page/{page}")
def job_page(job_id: str, page: int):
    """Rendered HTML + raw text for a single page (lazy-loaded by the viewer)."""
    job_dir = _require_done(job_id)
    text = (job_dir / "converted.md").read_text(encoding="utf-8")
    chunk = _split_pages(text).get(page, "")
    html = md_lib.markdown(chunk, extensions=["tables", "fenced_code", "sane_lists", "nl2br"])
    html = re.sub(r'(<img[^>]*\bsrc=")images/', rf'\1/api/jobs/{job_id}/images/', html)
    return {"html": html, "raw": chunk}


@app.get("/api/jobs/{job_id}/download")
def job_download(job_id: str):
    job_dir = _require_done(job_id)
    job = job_manager.get_job(job_id) or {}
    stem = Path(job.get("filename", "converted")).stem

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(job_dir / "converted.md", arcname="converted.md")
        images_dir = job_dir / "images"
        if images_dir.exists():
            for img in sorted(images_dir.glob("*")):
                if img.is_file():
                    zf.write(img, arcname=f"images/{img.name}")
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{stem}_markdown.zip"'},
    )
