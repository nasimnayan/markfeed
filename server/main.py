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
from fastapi import FastAPI, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from converters.chunker import PAGE_SPLIT_RE, build_chunks, split_pages
from converters.postprocess import slugify as _toc_slugify
from server.jobs import JobManager

# Shared markdown rendering config. The `toc` extension adds heading ids using the
# same slugify build_toc uses, so the generated Contents links resolve (Bengali too).
_MD_EXTENSIONS = ["tables", "fenced_code", "sane_lists", "nl2br", "toc"]
_MD_CONFIGS = {"toc": {"slugify": _toc_slugify}}

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


app = FastAPI(title="MarkFeed", lifespan=lifespan)
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
    preprocess: bool = Form(True),
    make_searchable: bool = Form(False),
    gen_toc: bool = Form(False),
    preset: str | None = Form(None),
    start_page: int | None = Form(None),
    end_page: int | None = Form(None),
    batch_id: str | None = Form(None),
):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (
        ".pdf", ".docx", ".csv", ".xls", ".xlsx",
        ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif",
    ):
        raise HTTPException(400, "Only PDF, Word, CSV, Excel and image files are supported")
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(400, "Uploaded file is empty")

    start = (start_page - 1) if start_page and start_page > 0 else 0
    end = end_page

    # Extraction mode is heavy (slow + can segfault on this CPU box), but it's a
    # local, no-cost tool — so the old per-run page cap is no longer enforced.
    # The user chooses "all pages" or a range, same as plain mode; the UI just
    # warns that a range is safer for very long books. See converters/limits.py.

    job_id = job_manager.create_job(
        file.filename or f"upload{suffix}",
        file_bytes,
        {
            "file_type": suffix.lstrip("."),  # pdf / docx / csv / xls / xlsx
            "lang": lang,
            "dpi": dpi,
            "use_layout": use_layout,
            "preprocess": preprocess,
            "make_searchable": make_searchable,
            "gen_toc": gen_toc,
            "preset": preset,
            "start_page": start,
            "end_page": end,
            "batch_id": batch_id,
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


@app.post("/api/jobs/{job_id}/resume")
def resume_job(job_id: str):
    """Continue a crashed PDF job from the pages it already finished."""
    result = job_manager.resume_job(job_id)
    if result == "not_found":
        raise HTTPException(404, "Job not found")
    if result == "running":
        raise HTTPException(409, "Job is already running")
    if result == "not_resumable":
        raise HTTPException(400, "Only PDF conversions can be resumed")
    return {"resuming": job_id}


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    result = job_manager.delete_job(job_id)
    if result == "not_found":
        raise HTTPException(404, "Job not found")
    if result == "running":
        raise HTTPException(409, "Cannot delete a job that is currently running")
    return {"deleted": job_id}


def _require_done(job_id: str) -> Path:
    job_dir = job_manager._job_dir(job_id)
    if not (job_dir / "converted.md").exists():
        raise HTTPException(404, "Result not ready")
    return job_dir


@app.get("/api/jobs/{job_id}/markdown", response_class=PlainTextResponse)
def job_markdown(job_id: str):
    job_dir = _require_done(job_id)
    return (job_dir / "converted.md").read_text(encoding="utf-8")


@app.get("/api/jobs/{job_id}/chunks.json")
def job_chunks(job_id: str):
    """RAG-ready chunked JSON (one chunk per page/section). Generated on request."""
    import json

    job_dir = _require_done(job_id)
    payload = json.dumps(build_chunks(job_dir), ensure_ascii=False, indent=2)
    stem = Path((job_manager.get_job(job_id) or {}).get("filename", "document")).stem
    return Response(
        content=payload,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{stem}_chunks.json"'},
    )


@app.get("/api/jobs/{job_id}/preview", response_class=HTMLResponse)
def job_preview(job_id: str):
    job_dir = _require_done(job_id)
    text = (job_dir / "converted.md").read_text(encoding="utf-8")
    html = md_lib.markdown(text, extensions=_MD_EXTENSIONS, extension_configs=_MD_CONFIGS)
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


@app.get("/api/jobs/{job_id}/searchable.pdf")
def job_searchable_pdf(job_id: str):
    """The merged searchable PDF (original-looking pages + invisible OCR text)."""
    job_dir = job_manager._job_dir(job_id)
    pdf_path = job_dir / "searchable.pdf"
    if not pdf_path.exists():
        raise HTTPException(404, "Searchable PDF not available for this job")
    job = job_manager.get_job(job_id) or {}
    stem = Path(job.get("filename", "document")).stem
    return FileResponse(
        str(pdf_path), media_type="application/pdf", filename=f"{stem}_searchable.pdf"
    )


@app.get("/api/jobs/{job_id}/previews/{name}")
def job_preview_image(job_id: str, name: str):
    safe = Path(name).name  # path-traversal guard
    img_path = job_manager._job_dir(job_id) / "previews" / safe
    if not img_path.exists():
        raise HTTPException(404, "Preview not found")
    return FileResponse(str(img_path))


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


@app.get("/api/jobs/{job_id}/live")
def job_live(job_id: str):
    """Pages converted so far (works while the job is still running).

    Powers the live, during-conversion compare view. Unlike /compare it does not
    require the whole document to be finished — it reads live.json, which the
    worker rewrites after every page.
    """
    job_dir = job_manager._job_dir(job_id)
    if not job_dir.exists():
        raise HTTPException(404, "Job not found")
    import json

    live_path = job_dir / "live.json"
    try:
        live = json.loads(live_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        live = {"pages": []}
    pages = [p for p in live.get("pages", []) if p.get("preview")]
    return {"pages": pages}


@app.get("/api/jobs/{job_id}/page/{page}")
def job_page(job_id: str, page: int):
    """Rendered HTML + raw text for a single page (lazy-loaded by the viewer).

    Works both after completion (reads the combined converted.md) and mid-run
    (falls back to the per-page file the worker writes for the live compare view).
    """
    job_dir = job_manager._job_dir(job_id)
    combined = job_dir / "converted.md"
    if combined.exists():
        chunk = split_pages(combined.read_text(encoding="utf-8")).get(page, "")
    else:
        per_page = job_dir / "pages" / f"{page}.md"
        if not per_page.exists():
            raise HTTPException(404, "Page not ready")
        chunk = PAGE_SPLIT_RE.sub("", per_page.read_text(encoding="utf-8")).strip()
    html = md_lib.markdown(chunk, extensions=_MD_EXTENSIONS, extension_configs=_MD_CONFIGS)
    html = re.sub(r'(<img[^>]*\bsrc=")images/', rf'\1/api/jobs/{job_id}/images/', html)

    # Per-page OCR confidence (whole-page OCR only) for the verify view.
    conf = None
    conf_path = job_dir / "conf" / f"{page}.json"
    if conf_path.exists():
        import json

        try:
            conf = json.loads(conf_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            conf = None
    return {"html": html, "raw": chunk, "conf": conf}


def _build_confidence_report(job_dir: Path) -> str | None:
    """Build confidence_report.md from result.json rows. Returns None if unavailable."""
    result_file = job_dir / "result.json"
    if not result_file.exists():
        return None
    try:
        import json as _json

        data = _json.loads(result_file.read_text(encoding="utf-8"))
        label_col = data.get("label_col", "page")
        rows = data.get("pages") or data.get("sections") or []
        if not rows:
            return None
    except Exception:
        return None

    def _bucket(conf: float | None) -> tuple[str, str]:
        if conf is None:
            return "N/A", "—"
        if conf >= 85:
            return "Good", f"{conf:.1f}%"
        if conf >= 70:
            return "Ok", f"{conf:.1f}%"
        return "Poor", f"{conf:.1f}%"

    scored = [r for r in rows if r.get("mean_conf") is not None]
    unscored_count = len(rows) - len(scored)
    if scored:
        overall_mean: float | None = sum(r["mean_conf"] for r in scored) / len(scored)
    else:
        overall_mean = None
    overall_quality, overall_str = _bucket(overall_mean)

    lines = [
        "# OCR Confidence Report",
        "Generated by MarkFeed",
        "",
        "## Summary",
        f"- Total pages: {len(rows)}",
        f"- Pages with confidence data: {len(scored)} (plain OCR only)",
        f"- Pages without confidence data: {unscored_count} (digital or layout/hybrid — see note)",
        f"- Overall mean confidence: {overall_str} (across scored pages only)",
        f"- Overall quality: {overall_quality}",
        "",
        "> Note: Confidence scores are available only for scanned pages processed with plain OCR.",
        "> Digital PDF pages and pages processed with layout extraction (Advanced mode) do not",
        "> produce confidence scores — this is a current limitation.",
        "",
        "## Per-Page Results",
        "",
        "| Page | Score | Quality | Low-conf words |",
        "|------|-------|---------|----------------|",
    ]

    _EMOJI = {"Good": "✅", "Ok": "⚠️", "Poor": "❌", "N/A": "—"}
    needs_review: list[str] = []
    for row in rows:
        page_label = str(row.get(label_col, "?"))
        conf = row.get("mean_conf")
        low = row.get("low_conf_count")
        quality, score_str = _bucket(conf)
        # Low-conf word count is only meaningful for scored pages; N/A pages
        # carry a stored 0 that would misleadingly read as "0 low-conf words".
        low_str = str(low) if (conf is not None and low is not None) else "—"
        emoji = _EMOJI.get(quality, "")
        display = f"{emoji} {quality}" if emoji != "—" else quality
        lines.append(f"| {page_label} | {score_str} | {display} | {low_str} |")
        if conf is None:
            needs_review.append(f"- Page {page_label} — No score (digital/hybrid page)")
        elif conf < 70:
            needs_review.append(
                f"- Page {page_label} — Score: {conf:.1f}% (poor) — recommend manual check"
            )

    lines += ["", "## Pages Needing Review", ""]
    lines.extend(needs_review if needs_review else ["_All scored pages meet the OK threshold (≥70%)._"])
    return "\n".join(lines)


def _build_html_export(job_dir: Path, stem: str, md_text: str) -> str:
    """Render converted.md → self-contained HTML with base64-embedded images."""
    import base64 as _b64
    from datetime import date as _date
    from html import escape as _esc

    html_body = md_lib.markdown(md_text, extensions=_MD_EXTENSIONS, extension_configs=_MD_CONFIGS)

    images_dir = job_dir / "images"

    def _embed(m: re.Match) -> str:
        src = m.group(1)
        if src.startswith("images/"):
            img_path = images_dir / src[len("images/"):]
            if img_path.is_file():
                ext = img_path.suffix.lstrip(".").lower()
                mime = {
                    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                    "gif": "image/gif", "webp": "image/webp",
                }.get(ext, "image/png")
                b64 = _b64.b64encode(img_path.read_bytes()).decode()
                return f'src="data:{mime};base64,{b64}"'
        return m.group(0)

    html_body = re.sub(r'src="([^"]+)"', _embed, html_body)
    today = _date.today().isoformat()
    safe_stem = _esc(stem)
    css = (
        "body{font-family:Georgia,'Times New Roman',serif;max-width:800px;margin:2rem auto;"
        "padding:0 1rem;line-height:1.7;color:#1a1a1a}"
        "h1,h2,h3,h4{font-family:system-ui,sans-serif;margin-top:2em}"
        "table{border-collapse:collapse;width:100%;margin:1em 0}"
        "th,td{border:1px solid #ccc;padding:.4em .8em;text-align:left}"
        "th{background:#f5f5f5}"
        "img{max-width:100%;height:auto;display:block;margin:1em auto}"
        "pre,code{background:#f5f5f5;padding:.2em .4em;border-radius:3px;font-size:.9em}"
        "pre{padding:1em;overflow-x:auto}"
        "@media print{body{max-width:none}img{page-break-inside:avoid}}"
        ".mf-footer{margin-top:3em;padding-top:1em;border-top:1px solid #ccc;"
        "font-size:.8em;color:#666;font-family:system-ui,sans-serif}"
    )
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f"<title>{safe_stem}</title>\n<style>{css}</style>\n</head>\n<body>\n"
        "<!-- Math rendering not supported — equations appear as plain text -->\n"
        f"{html_body}\n"
        f'<div class="mf-footer">Generated by MarkFeed &middot; {safe_stem} &middot; {today}</div>\n'
        "</body>\n</html>"
    )


@app.get("/api/jobs/{job_id}/download")
def job_download(job_id: str):
    job_dir = _require_done(job_id)
    job = job_manager.get_job(job_id) or {}
    stem = Path(job.get("filename", "converted")).stem
    folder = f"markfeed_{stem}"

    import json

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Core markdown
        md_path = job_dir / "converted.md"
        md_text = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
        if md_text:
            zf.write(md_path, arcname=f"{folder}/converted.md")

        # Extracted images
        images_dir = job_dir / "images"
        if images_dir.exists():
            for img in sorted(images_dir.glob("*")):
                if img.is_file():
                    zf.write(img, arcname=f"{folder}/images/{img.name}")

        # Searchable PDF
        searchable_pdf = job_dir / "searchable.pdf"
        if searchable_pdf.exists():
            zf.write(searchable_pdf, arcname=f"{folder}/searchable.pdf")

        # RAG-ready chunks (skip silently if generation fails, like the rest)
        try:
            zf.writestr(
                f"{folder}/chunks.json",
                json.dumps(build_chunks(job_dir), ensure_ascii=False, indent=2),
            )
        except Exception:
            pass

        # Self-contained rendered HTML (images base64-embedded)
        if md_text:
            html = _build_html_export(job_dir, stem, md_text)
            zf.writestr(f"{folder}/converted.html", html.encode("utf-8"))

        # Per-page OCR confidence report
        conf_report = _build_confidence_report(job_dir)
        if conf_report:
            zf.writestr(f"{folder}/confidence_report.md", conf_report.encode("utf-8"))

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{folder}.zip"'},
    )


@app.get("/api/batch/{batch_id}/download")
def batch_download(batch_id: str):
    matches = []
    for job_dir in job_manager.jobs_root.iterdir():
        if not job_dir.is_dir():
            continue
        job = job_manager.get_job(job_dir.name)
        if job and job.get("batch_id") == batch_id and (job_dir / "converted.md").exists():
            matches.append(job)
    if not matches:
        raise HTTPException(404, "No completed files found for this batch")

    matches.sort(key=lambda j: j.get("created_at") or "")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for idx, job in enumerate(matches, start=1):
            job_dir = job_manager._job_dir(job["job_id"])
            stem = Path(job.get("filename", "converted")).stem
            folder = f"{idx:02d}_{stem}"
            zf.write(job_dir / "converted.md", arcname=f"{folder}/converted.md")
            images_dir = job_dir / "images"
            if images_dir.exists():
                for img in sorted(images_dir.glob("*")):
                    if img.is_file():
                        zf.write(img, arcname=f"{folder}/images/{img.name}")
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="batch_{batch_id}.zip"'},
    )
