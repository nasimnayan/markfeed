# Product tiering — future direction (NOT implemented)

> Read [`product-vision.md`](product-vision.md) first — it sets the overall direction
> (Bangla digitization & AI knowledge prep). This file is the Basic/Advanced detail.

Decision (2026-06-17): **do not build capability registry, auth, payments, or accounts
now.** The app stays fully offline and self-hosted, with **all features functional for
everyone**. This file records how features would *naturally* classify if a Basic/Advanced
split is introduced later, so we can build in a tier-friendly way without committing to it.

**Update (2026-06-18):** a **display-only** Free/Advanced toggle now exists in the UI
(shows/hides Advanced controls — Extract diagrams & tables, Searchable PDF, Chunked JSON,
Confidence mode). It is *not* gating/auth/payment; every feature still runs for everyone.

## Guiding principles (followed while building Tier-1)
- **Converters stay tier-agnostic** — pure functions in `converters/*`; no tier logic.
  Any future gating lives only in the UI / API layer.
- **Every feature stays independently toggleable + side-effect-free** (e.g. lazy
  `chunks.json` endpoint, opt-in searchable PDF) → a tier line can be drawn later
  with no refactor.
- **Record which features a job used** in `job.json` (and echo into output metadata)
  → doubles as benchmark provenance and as a future tiering hook.
- **Presets** (Item 4) are the intended primary organizer — design them to bundle the
  "advanced" behaviors so the eventual line can follow presets, not rewiring.

## Natural classification (future only)

### Basic (core quality for everyone)
- Document conversion: PDF, Image, DOCX, Excel/CSV
- PDF OCR, Image OCR, Bangla + English OCR
- **OCR preprocessing** (deskew/denoise/contrast/shadow) — core quality, ON by default
- Markdown export, ZIP export
- Verify / compare view (read-only)
- Basic statistics
- Batch processing (small, ≤10 files)
- TOC generation (cheap, broadly useful)
- Document preset selector

### Advanced (future differentiators)
- Searchable PDF output
- Chunked JSON export / knowledge-base export
- OCR confidence scoring + low-confidence highlighting
- Editable verification / human-correction workflow
- Advanced analytics (confidence histograms, per-page quality)
- Granular/manual preprocessing controls (per-stage toggles, strength)
- Large-scale batch / knowledge-base builder

### Strongest Advanced differentiators (ranked)
1. Editable verification + human-correction workflow (production pipeline).
2. AI knowledge-prep outputs (chunked JSON + KB export + searchable PDF).
3. Confidence scoring + low-confidence highlighting (QA at scale).

> Preprocessing is intentionally Basic — it makes Basic genuinely good, rather than
> being a paid differentiator. Everything above is built ungated for now.
