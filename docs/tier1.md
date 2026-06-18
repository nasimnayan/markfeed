# Tier 1 — Bangla Digitization & AI Knowledge Prep

Tracking doc for the Tier 1 work. **The plan and every change are recorded here.**
Product direction: offline-first / no-LLM by default; prioritize OCR quality and
AI-ingestible output.

## Scope (4 items)
1. **OCR preprocessing** — deskew, denoise, contrast, shadow removal.
2. **Chunked JSON export** — RAG/knowledge-base ingestion.
3. **Searchable PDF** — original page image + invisible OCR text layer.
4. **TOC generation + document presets**.

## Confirmed decisions
- Chunking: **base-unit only** (one chunk per page/section); sub-chunk params present but off.
- Searchable PDF: **full mixed merge** (OCR layer for scanned pages, original copied for digital).
- Preprocessing: **ON by default** for scanned pages + images; never on digital/docx/csv.

## Shared plumbing
New job options flow UI → `server/main.py` (Form) → `server/jobs.py` (job.json) →
`worker.py` → converters: `preprocess`, `make_searchable`, `gen_toc`, `preset`.
New dependency: `opencv-python-headless` (+ `numpy`).

---

## Progress log

### Item 1 — OCR preprocessing  ·  status: DONE (2026-06-17)
Order chosen: build #1 first as a standalone increment for quality review.

Changes:
- [x] `converters/preprocess.py` (new) — `enhance(img, *, deskew, denoise, contrast, shadow)`,
      color-preserving (LAB L-channel), defensive (returns original on any failure).
- [x] `converters/pdf_converter.py` — `preprocess_scans` arg; enhances the OCR input in
      the scanned branch **before** OCR; **preview keeps the original render**.
- [x] `converters/image_converter.py` — `preprocess_scans` arg; enhance before OCR; preview = original.
- [x] `worker.py` — reads `preprocess` flag, passes to convert_pdf/convert_image.
- [x] `server/main.py` — `preprocess: bool = Form(True)`, stored in job options.
- [x] `server/jobs.py` — persists `preprocess` in job.json (default True).
- [x] `server/static/index.html` + `app.js` — "Enhance scan quality" toggle (default on,
      shown only for scanned PDF + image; explicit true/false set in FormData + batch).
- [x] `convert.py` — `--no-preprocess` CLI flag for parity.
- [x] `requirements.txt` — added `opencv-python-headless` + `numpy`.
- [x] Verified: byte-compile clean; unit OCR test; end-to-end worker test.

Pipeline (final, tuned): estimate skew on raw luminance → **denoise → shadow
removal → gentle CLAHE (clip 1.5)** → deskew at the end.

Key findings during build:
- **`minAreaRect` deskew flipped wide text blocks to ~90°** (OpenCV 4.x angle
  ambiguity) → replaced with a **projection-profile** angle search (±15°, 0.5° step,
  downscaled to 1000px for speed).
- **CLAHE before denoise destroyed OCR** (amplified background noise to speckle →
  Tesseract returned empty) → reordered to denoise-first + gentler clip; skew is
  measured before tonal ops (which otherwise flatten the profile).
- Skew estimated on the raw channel up front; tonal ops would otherwise ruin it.

Test results (synthetic "quick brown fox", 6° skew + gaussian noise σ25, eng):
- skewed+noisy BEFORE 5–6/8 words → **enhanced AFTER 8/8** (3 trials).
- clean upright: 8/8 → 8/8 (no regression).
- worker E2E (png job, preprocess on): exit 0, status done, text fully recovered,
  original-render preview saved.

### Item 3 — Searchable PDF  ·  status: DONE (2026-06-17)
Built first per the reviewed priority queue (Searchable PDF → Chunked JSON → TOC →
Confidence → Editable verify).

Changes:
- [x] `converters/searchable.py` (new) — `page_pdf_from_image` (Tesseract PDF output:
      image + invisible text layer, embed capped to 2600px), `page_pdf_from_pdf_page`
      (copies a digital page via PyMuPDF), `merge_to_file` (orders + merges pages).
- [x] `converters/pdf_converter.py` — `searchable_callback` arg; digital pages copied,
      OCR pages embed the **enhanced** image we OCR'd (so the text layer aligns).
- [x] `converters/image_converter.py` — same `searchable_callback` for the single page.
- [x] `worker.py` — writes per-page PDFs to `searchable_pages/{i:05d}.pdf`, merges to
      `searchable.pdf` after conversion (guarded by `make_searchable`).
- [x] `server/main.py` — `make_searchable: bool = Form(False)`; `GET /searchable.pdf`
      endpoint; included in the download zip.
- [x] `server/jobs.py` — persists `make_searchable` in job.json.
- [x] UI — "Also create a searchable PDF" toggle (pdf+image, default off) + a Download
      tab button shown via a HEAD check only when the file exists.

Decision honoured: **full mixed merge** — digital pages keep their real text, scanned
pages get an OCR layer, merged strictly in page order.

Tests (synthetic, eng):
- 2-page scanned PDF (no source text layer) → `searchable.pdf` with correct text on
  both pages; worker exit 0.
- Mixed digital+scanned PDF → page 0 keeps digital text, page 1 gets OCR text, order
  preserved.

Known limitation: embedded page images make the PDF sizeable (~few MB/page at full
res); future optimisation = JPEG-compress the embed. Not gating delivery.

### Item 2 — Chunked JSON export  ·  status: DONE (2026-06-17)
Changes:
- [x] `converters/chunker.py` (new) — canonical page splitter (`split_pages`,
      `PAGE_SPLIT_RE`) + `split_sections` + `build_chunks(job_dir, chunk_chars=0,
      overlap=0)`. Base-unit chunks (1 per page / heading-section); sub-chunking params
      wired but default off (reviewed decision). Recomputes per-chunk stats; extracts
      image links; emits a `document.features` provenance block (preprocess/use_layout/
      make_searchable) — doubles as the future-tiering hook.
- [x] `server/main.py` — imports the splitter from chunker (removed the local
      duplicate `_split_pages`/`_PAGE_SPLIT_RE`); `GET /chunks.json` endpoint
      (`ensure_ascii=False`); `chunks.json` added to the download zip.
- [x] UI — "Chunked JSON (.json)" button in the Download tab (works for any completed
      job, so always shown).

Schema: `{document:{filename,file_type,language,created_at,unit,chunk_count,features},
chunks:[{chunk_id,source_page|source_section,text,word_count,char_count,image_count,
table_count,images[]}]}`.

Tests: PDF → page-based, **1-based** pages, Bangla preserved, image links extracted,
features present; XLSX → section-based on `##` headings with correct table counts;
valid JSON round-trip. All assertions passed.

### Item 4 — TOC + presets  ·  status: DONE (2026-06-17)
Changes:
- [x] `converters/postprocess.py` (new) — `slugify` (Unicode/Bengali-safe) +
      `build_toc(markdown, max_level=3)`: prepends a linked "## Contents" outline from
      `#`-headings; returns text unchanged when there are none (plain OCR).
- [x] `worker.py` — applies `build_toc` to the markdown when `gen_toc`, before writing
      `converted.md`.
- [x] `server/main.py` — `gen_toc` + `preset` form params; enabled python-markdown's
      `toc` extension with the **same** slugify so preview anchors resolve.
- [x] `server/jobs.py` — persists `gen_toc` + `preset`; `chunker` echoes both in the
      JSON `document.features` block.
- [x] UI — preset `<select>` (Plain / Research / Policy / Book) that bundles options
      via a JS `PRESETS` map + `applyPreset` (fires dependent handlers); "Generate
      table of contents" checkbox. Wired into single + batch submit.

Tests: TOC nesting + duplicate-heading dedup (`methods`, `methods_1`) matches
python-markdown; Bengali heading slug resolves (TOC link target == rendered heading
id); flat text unchanged; all anchors resolve.

### Confidence scoring  ·  status: DONE (2026-06-17)
Changes:
- [x] `converters/confidence.py` (new) — `ocr_with_confidence(img, lang)` via
      `image_to_data` (same OCR pass): returns reconstructed text, mean confidence,
      low-confidence count (<60), and highlighted HTML (low-conf words wrapped in
      `<span class="lc">`, paragraph/line structure preserved, escaped).
- [x] `pdf_converter.py` / `image_converter.py` — use it for whole-page OCR (plain
      mode + layout fallback); write `conf/{page}.json` (mean/low/html) via new
      `conf_dir` arg; add `mean_conf` + `low_conf_count` to the page row.
- [x] `worker.py` — passes `conf_dir=job_dir/"conf"`.
- [x] `server/main.py` — `/page/{page}` now returns `conf` (mean/low/html) when present.
- [x] UI — verify view: a **Confidence** view mode (highlighted text) + a colour-coded
      per-page badge ("OCR 87% · N low-confidence"); Stats gains an "Avg Conf" column.
      CSS for `.lc` highlight + `.conf-badge`.

Scope: whole-page OCR only (layout mode does its own region OCR → no per-word conf).

Tests: E2E image job → `mean_conf`/`low_conf_count` on the row + `conf/0.json` written;
empty/no-text page handled (mean None, no crash); low-confidence span wrapping verified
(words wrapped with `title="NN% confidence"`, structure + escaping correct).

### Editable verification  ·  status: TODO (last in queue)
