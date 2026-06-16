# MarkFeed — OCR Evaluation / Benchmark Harness

## Context

MarkFeed reports *volume* stats (word/char/table counts) but **no accuracy**. Before
publishing — and before swapping or adding OCR engines — we need an objective way to
answer "how good is the Bengali/English output, and did a change make it better or
worse." This builds an in-repo evaluation harness that scores converter output against
hand-verified ground truth using the standard OCR metrics (CER / WER), reports per
document type, and can act as a regression gate.

Decisions (confirmed with user):
- **Build the eval harness first** — it's the prerequisite for any accuracy claim or
  engine A/B.
- **Tesseract stays the default**; future engines (Indic tessdata, Surya) will be
  opt-in and chosen by *measured* numbers from this harness.

Constraint preserved: everything offline, pure-Python scoring (no cloud, no LLM).
Reuses the existing converter entry points — no changes to conversion code in this step.

## Approach

A new top-level `eval/` package. Each test case is a folder holding a source document
and its 100%-correct `expected.md`. `eval/run.py` converts each case via the existing
`convert_pdf` / `convert_docx` (exactly as `convert.py` calls them — see
`convert.py:111` and `:129`), scores output vs expected, prints a table, writes a JSON
report, and exits non-zero if any doc-type group is over its error threshold.

### Layout
```
eval/
  __init__.py
  cases/
    <case-id>/
      input.pdf | input.docx        # source document (or a page image)
      expected.md                   # hand-verified ground truth (UTF-8)
      meta.json                     # {lang, doc_type, use_layout, pages, source_committed}
  normalize.py                      # Unicode NFC + whitespace/markdown normalization
  metrics.py                        # cer(), wer(), and raw-markdown edit-distance
  run.py                            # iterate cases -> convert -> score -> report -> gate
  thresholds.json                   # per-doc-type CER/WER ceilings
  README.md                         # how to add a case; what doc_type values mean
```

`doc_type` values: `scanned_bn`, `scanned_en`, `mixed`, `digital`, `table`, `formula`
— so the report shows exactly where MarkFeed is weak (Bengali conjuncts, tables, math).

### `eval/normalize.py`
- `normalize_text(md) -> str`: strip Markdown to prose, then `unicodedata.normalize("NFC", …)`,
  collapse whitespace, strip. **NFC is essential** — Bengali has many equivalent codepoint
  sequences and without it we'd over-count errors. Reuse the markdown-stripping regex from
  `converters/stats.py:_strip_markdown` (import or mirror it) so "text" means the same thing
  the stats already mean.
- `normalize_markdown(md) -> str`: NFC + whitespace only (keeps `#`, `|`, `![]()`), for a
  structure-sensitive score.

### `eval/metrics.py`
- Use **`jiwer`** (pure-Python, offline, on PyPI) for `cer()` and `wer()` (Levenshtein-based,
  the recognized standard). Add `jiwer` to `requirements.txt`.
- `score_case(expected_md, actual_md) -> dict` returns:
  `{cer, wer, md_editdist}` where `cer`/`wer` run on `normalize_text` output and
  `md_editdist` is a normalized edit distance on `normalize_markdown` output (cheap
  structure/reading-order signal; full **TEDS** for tables is a documented Phase-2 add-on,
  not in this step).

### `eval/run.py`
- Import `converters.tesseract_config` for its side effect (sets the Tesseract path), same
  as the app does, so it runs headless.
- For each case folder: read `meta.json`; dispatch on the input file —
  `.pdf` → `convert_pdf(bytes, images_dir, lang=…, use_layout=…, start_page/end_page from pages)`,
  `.docx` → `convert_docx(bytes, images_dir)` — into a throwaway temp images dir.
- Score with `metrics.score_case`. Collect rows; aggregate (mean) per `doc_type` and overall.
- Print a Rich table (reuse the Rich style already in `convert.py`) and write
  `eval/report.json` (+ optional `report.html`).
- `--gate`: load `thresholds.json`; if any doc-type mean CER/WER exceeds its ceiling, exit 1.
  This is the "don't ship a regression / this is our standard" check.
- CLI flags: `--cases-dir`, `--filter <doc_type>`, `--gate`, `--json-out`.

### `eval/cases/` content & licensing
- Ship **one tiny non-copyrighted sample** (e.g. a short public-domain or self-written
  English+Bengali snippet rendered to a small PDF) so `python -m eval.run` works out of the
  box for anyone cloning the repo.
- **Real book pages are copyrighted** (CLAUDE.md forbids committing `chemistry-1.pdf`). In
  `meta.json`, `source_committed: false` marks cases whose `input.*` must be gitignored;
  add `eval/cases/*/input.*` (except the sample) to `.gitignore`, keeping `expected.md` +
  `meta.json` tracked so the *test definition* lives in git even when the scan can't.
- `README.md`: step-by-step "convert a page, hand-fix the Markdown into expected.md, set
  doc_type" so the user can grow the set toward the ~5–10k words needed for a stable estimate.

## Files touched / created

- `eval/__init__.py`, `eval/normalize.py`, `eval/metrics.py`, `eval/run.py`,
  `eval/thresholds.json`, `eval/README.md` **(all new)**
- `eval/cases/sample-en-bn/` **(new — the committed runnable sample)**
- `requirements.txt` (add `jiwer`)
- `.gitignore` (ignore real-scan `input.*` under `eval/cases/`)
- `CLAUDE.md` (short "Evaluation" section: how to run, what the gate means)

## Reused existing code

- `converters/pdf_converter.py: convert_pdf` and `converters/docx_converter.py: convert_docx`
  — same calls as `convert.py:111` / `:129`.
- `converters/stats.py: _strip_markdown` — for consistent prose extraction.
- `converters/tesseract_config.py` — import for Tesseract path side effect.
- Rich table styling pattern from `convert.py:build_stats_table`.

## Verification

1. `pip install -r requirements.txt` (pulls `jiwer`).
2. `python -m eval.run` → prints a per-case + per-doc-type CER/WER/edit-distance table for
   the committed sample and writes `eval/report.json`.
3. **Sanity check the metric:** copy `expected.md` to a fake output and confirm CER/WER = 0;
   hand-introduce a few character errors and confirm CER rises proportionally; verify a
   Bengali NFC vs NFD variant of the same text still scores 0 (proves normalization works).
4. `python -m eval.run --gate` with a deliberately strict threshold → exits non-zero;
   with a lenient threshold → exits 0. Confirms the publishing gate.
5. Add one real scanned Bengali page locally (gitignored) → confirm it appears in the
   report under `scanned_bn` and produces a realistic CER (expect notably higher than English).

## Later (out of scope here, tracked for next steps)

- **TEDS** table-structure scoring (needs `apted`/`lxml`) for `doc_type: table`.
- Pluggable OCR backend + **Surya (CPU)** / **Indic-OCR `ben` traineddata**, compared head
  to head on this harness; winner offered as an opt-in "Accurate" mode (Tesseract stays default).
- Bengali post-correction (NFC at output time, spacing fix, dictionary pass).
- Publishing prep (licensing audit, Docker/installer bundle, docs, "100% offline" framing).

---

## Appendix — Research background (why this plan)

**Is the current stack standard/best for Bengali + English?** A solid offline *baseline*,
not state-of-the-art for Bengali. Tesseract LSTM with `tessdata_best` reports ~91% char /
~76% word on printed Bengali in studies; weak spots are structural — compound characters
(যুক্তাক্ষর), before-consonant dependent vowels, and word-spacing. English is fine (~92%+).

**Better offline options to A/B later:** Indic-OCR `ben` traineddata (cheap drop-in fix for
glyph ordering); Surya OCR (transformer, 90+ langs incl. Bengali, runs on CPU offline).
VLM parsers (dots.ocr, olmOCR-2, PaddleOCR-VL, Marker, Docling) are the 2025/26 SOTA on
OmniDocBench but are GPU/LLM-class — they break the offline/no-LLM identity, so keep them
as a possible *optional* future backend, never the default.

**How we measure (the standard):** CER/WER are the recognized OCR metrics; TEDS for tables
and normalized edit-distance for whole-document structure (OmniDocBench / READoc method).
Apply Unicode NFC before scoring. Build ~5–10k words of ground truth for a stable estimate.

Sources: OmniDocBench (CVPR 2025); READoc; dinglehopper (CER/WER tool); Indic-OCR tessdata;
Surya OCR (datalab-to); printed-Bengali Tesseract accuracy + Bangla-CrossHair studies.
