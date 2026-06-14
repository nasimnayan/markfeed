# 📄 Folio — Documents to Markdown, fully offline

Folio converts **scanned PDFs, digital PDFs, and Word (.docx)** files into clean
**Markdown** — with extracted images, tables, a per-page accuracy stats table, and
a side-by-side **verify** view (original scan vs converted text).

It runs **100% offline. No LLM. No cloud APIs.** Built with open-source OCR
(Tesseract), layout detection (PaddleOCR), and table extraction (img2table). It
has first-class support for **Bengali + English** scanned books.

> Best for digitising scanned textbooks and documents where you need the text out,
> want to keep tables/figures, and need to *verify* OCR quality page by page.

## ✨ Features

- **Three inputs:** scanned PDF (OCR), digital/text PDF, and DOCX.
- **Two scan modes:**
  - *Plain text* — fast, stable whole-page OCR (no page limit).
  - *Extract diagrams & tables* — detects figures → embedded images, tables →
    Markdown tables, headings, and reading order.
- **Verify view** — original page image on the left, converted Markdown on the
  right, page-by-page, with a Rendered/Raw toggle.
- **Per-page stats** — word / character / image / table / formula counts + totals.
- **Downloads** — `.md` file or a `.zip` with Markdown + extracted images.
- **Recent jobs** sidebar to revisit past conversions.
- **Crash-isolated** — each conversion runs in its own process, so a failure never
  takes down the server; you get a one-click retry.

## 🧰 Tech

FastAPI · PyMuPDF / pymupdf4llm · Tesseract OCR · PaddleOCR (PP-DocLayout) ·
img2table · mammoth + markdownify · vanilla HTML/CSS/JS (no framework, no CDN).

## 🚀 Quick start (local)

### 1. Install Tesseract OCR
- **Windows:** `winget install tesseract-ocr.tesseract`
- **macOS:** `brew install tesseract tesseract-lang`
- **Linux:** `sudo apt install tesseract-ocr tesseract-ocr-ben tesseract-ocr-eng`

For Bengali, ensure `ben.traineddata` is in your Tesseract `tessdata` folder
(the high-quality version is in [tessdata_best](https://github.com/tesseract-ocr/tessdata_best)).

### 2. Install Python deps
```bash
pip install -r requirements.txt
```

### 3. Run
```bash
python run.py
```
Open **http://localhost:8800**. Upload a file, pick options, and convert.

> First run of *Extract diagrams & tables* downloads the PaddleOCR layout model
> (~hundreds of MB) once.

## 📁 Project layout

| Path | Purpose |
|------|---------|
| `run.py` | Launcher (opens browser, starts the server) |
| `convert.py` | Standalone CLI (`python convert.py file.pdf -o out`) |
| `worker.py` | Isolated per-job conversion subprocess |
| `converters/` | The conversion engine (PDF, DOCX, layout OCR, stats) |
| `server/` | FastAPI app + static single-page UI |

See [CLAUDE.md](CLAUDE.md) for full architecture and design notes.

## ⚠️ Known limitations

- **Math / equations** OCR is rough (Tesseract struggles with subscripts and
  chemistry notation). Prose and tables come through well.
- **Low-quality scans** reduce table/figure detection accuracy — use the verify
  view to check.

## 🌐 Hosting

Folio is a **local/self-hosted** tool by design (it needs the Tesseract binary,
PaddleOCR models, long-running processes, and a writable disk). It **cannot run on
serverless platforms like Vercel/Netlify.** To host a shared instance, use a
container host with persistent compute (Docker on a VPS, Render, Railway, Fly.io,
or Hugging Face Spaces). A `Dockerfile` can be added for this — see issues.

## 🤝 Contributing

Contributions welcome! Good first areas:
- Better math/formula handling (e.g., an optional formula-recognition model)
- More table layouts and languages
- A Dockerfile + hosted demo
- UI polish and accessibility

Please open an issue to discuss substantial changes first.

## 📜 License

MIT (suggested — update as you prefer).
