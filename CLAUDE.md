# CLAUDE.md — Folio

Context for future Claude Code sessions working on this project. Read this first.

## What this is

**Folio** is a fully-offline web app that converts **scanned PDFs, digital PDFs,
and Word (.docx)** files into clean **Markdown**, with a per-page accuracy stats
table and a side-by-side **verify** view (original scan vs converted text). It was
built primarily for OCR of **Bengali + English** scanned textbooks.

**No LLM, no cloud APIs.** Everything runs locally with open-source packages
(PyMuPDF, Tesseract, PaddleOCR layout model, img2table, mammoth, FastAPI).

## How to run

```
pip install -r requirements.txt
# Requires the Tesseract binary + Bengali/English traineddata installed (see below)
python run.py            # starts the server and opens http://localhost:8800
```

- Server: `uvicorn server.main:app --host 127.0.0.1 --port 8800`
- **Port 8800** is used because 8000 clashed with another local server on this
  machine. If 8800 is busy, the launcher errors — free it or change the port in
  `run.py` and `server/main.py` is port-agnostic (port is set by uvicorn args).

### Tesseract dependency
- Tesseract 5.x must be installed. On this machine it's at
  `C:\Users\<user>\AppData\Local\Programs\Tesseract-OCR\tesseract.exe` (winget).
- It is **not on PATH**, so `converters/tesseract_config.py` auto-detects it and
  (a) sets `pytesseract.tesseract_cmd`, (b) prepends the dir to `PATH` (img2table
  shells out to the bare `tesseract` command, so it needs PATH).
- Bengali traineddata (`ben.traineddata`, tessdata_best) must be in the Tesseract
  `tessdata` folder for `lang=ben`/`ben+eng`.

## Architecture

Conversion is heavy and PaddleOCR can crash natively (see history), so **each job
runs in its own OS subprocess**. A crash kills only that job; the FastAPI server
survives and reports a friendly error with a retry option.

```
Browser (static SPA)
   │  POST /api/jobs (upload + options)
   ▼
FastAPI (server/main.py)
   │  creates jobs/<uuid>/ , enqueues
   ▼
JobManager (server/jobs.py) — single async queue, one job at a time
   │  subprocess.Popen([python, worker.py, job_dir])
   ▼
worker.py  ── imports converters.* , writes progress.json / result.json /
              converted.md / error.json  (atomic writes)
```

Frontend polls `GET /api/jobs/<id>` every 1.5s for status/progress, then loads
preview / stats / compare / download.

### File map
```
run.py                      # launcher (opens browser, starts uvicorn on 8800)
convert.py                  # standalone CLI (rich progress + stats table) — still works
worker.py                   # isolated per-job subprocess entry point
requirements.txt
CLAUDE.md / README.md

converters/
  __init__.py
  tesseract_config.py       # finds tesseract.exe, sets cmd + PATH (imported for side effect)
  stats.py                  # word/char/image/table/formula counting (regex on markdown)
  pdf_converter.py          # routes digital vs scanned pages; saves page previews
  docx_converter.py         # mammoth -> HTML -> markdownify, image extraction, per-section stats
  layout_ocr.py             # diagram+table extraction (LayoutDetection + Tesseract + img2table)
  limits.py                 # extraction_page_cap(total) -> 10/20/all

server/
  __init__.py
  main.py                   # FastAPI routes
  jobs.py                   # JobManager: queue, subprocess spawn, crash detection
  static/index.html|style.css|app.js   # vanilla SPA, no framework, no CDN

jobs/                       # runtime per-job working dirs (gitignored)
```

### Per-job directory layout (jobs/<uuid>/)
- `input.pdf|input.docx`, `job.json` (options), `progress.json` (status/done/total),
  `result.json` (stats rows minus markdown, + `label_col`), `converted.md`,
  `error.json` (on failure), `images/` (embedded figures), `previews/` (downscaled
  page JPEGs for the compare view — NOT in the download zip).

## Conversion paths (converters/pdf_converter.py)

Per page, routed by whether the PDF page has an extractable text layer:
- **Digital page** (`page.get_text()` > 20 chars) → `pymupdf4llm.to_markdown()`,
  `source="digital"`.
- **Scanned page** → render to image, then:
  - plain mode (`use_layout=False`) → whole-page `pytesseract` (fast, stable).
  - extraction mode (`use_layout=True`) → `layout_ocr.process_page_image()`,
    with try/except fallback to plain Tesseract on any failure.
- Always saves a downscaled JPEG preview to `previews/` for the compare view.

### Layout extraction (converters/layout_ocr.py)
- PaddleOCR **standalone `LayoutDetection`** (`PP-DocLayout_plus-L`,
  `enable_mkldnn=False, cpu_threads=1`, `threshold=0.3`) → region boxes + labels.
- Reading-order sort (top-to-bottom band, then left-to-right) + IoU dedup.
- text/title → Tesseract; figure/chart → crop+save+embed; **table → img2table**
  (`borderless_tables=True`) → Markdown table (fallback to text); formula →
  inline Tesseract text (this book is formula-dense — cropping each = too many files).

## Important history / decisions

- **PP-StructureV3 was removed.** The original layout-aware mode used PaddleOCR's
  full `PPStructureV3` pipeline, which **segfaults** on this Windows/CPU box
  (exit code `3221225477` / `0xC0000005`) and cannot be fixed with flags
  (`enable_mkldnn=False`, `cpu_threads=1` both tried). The standalone
  `LayoutDetection` model is stable, so layout_ocr.py was rewritten to assemble
  only stable pieces. **Do not reintroduce PPStructureV3.**
- **Streamlit was removed** for the same reason: a single-process server dies when
  a worker segfaults. FastAPI + subprocess isolation replaced it.
- **Smart page cap** (`converters/limits.py`): extraction mode is capped per run —
  ≤20 pages → all; 21–200 → 20; >200 → 10. Plain text mode has **no cap**
  (a 700-page book at once is slow but stable). Enforced both in the UI
  (`app.js applyLayoutCap`) and backend (`server/main.py create_job`).
- **Verify/compare view is read-only** (user decided: no inline editing).

## Known limitations

- **Math/equation OCR is poor.** Tesseract mangles subscripts/superscripts and
  chemistry notation. Fixing well needs a formula model (PyTorch) that doesn't fit
  the offline/no-crash constraint. Bengali prose and tables are good.
- **Low-quality scans** reduce table/figure detection accuracy (watermarks, faint
  lines) — this is why the compare view matters.
- **Tables** in this book are mostly borderless; `borderless_tables=True` catches
  many but not all. Pure lists correctly fall back to text.

## Windows / environment gotchas

- Subprocess uses `subprocess.Popen` (NOT multiprocessing — avoids Windows `spawn`
  re-import + pickling issues). Worker env sets `PYTHONUTF8=1` + `PYTHONIOENCODING=utf-8`.
- All file writes use explicit `encoding="utf-8"` (Bengali). The terminal's cp1252
  can't print Bengali — write to files when inspecting.
- Atomic JSON writes = temp file + `Path.replace()` (atomic same-dir on Windows).
- A segfaulted worker exits non-zero with no `error.json`; JobManager detects that
  and marks the job `crashed` with `suggest_retry_without_layout=True`.

## Do NOT commit
- `chemistry-1.pdf` — copyrighted textbook (pdfcorner.com watermark). Test file only.
- `output/` — large prototype OCR dump of that book.
- `jobs/`, `.claude/`, logs, `__pycache__/`. See `.gitignore`.
