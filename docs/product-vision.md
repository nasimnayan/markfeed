# MarkFeed — Product Vision & Context

Canonical statement of MarkFeed's long-term direction. Technical decisions should align
with this. (Recorded 2026-06-18.)

## Positioning

Do **not** think of MarkFeed as a "PDF → Markdown converter." Think of it as a
**Bangla document digitization & AI knowledge-preparation platform**. Markdown is one
export among many.

The value chain is:

> Document → OCR → **Verification → Correction** → Archive → **AI-ready output**

The goal is **not** perfect OCR — it is a reliable human-in-the-loop pipeline that turns
real-world Bangla/English documents into trustworthy, searchable, AI-ingestible archives.

## What it does

- **Inputs:** scanned PDF, digital PDF, Word (.docx), Excel/CSV, images.
- **Outputs (Markdown is only one):** Markdown + extracted assets, Searchable PDF,
  Chunked JSON, knowledge-base export, structured metadata, statistics/analytics.

## Target users & documents

Researchers, students, NGOs, universities, archives, government institutions, and
organizations like BRAC. Optimized for **mixed Bangla + English** documents: BRAC
reports, government circulars, research papers, question banks, books, meeting minutes,
monitoring reports, survey reports.

## Product principles (do not violate)

1. **Offline-first** — works locally; no cloud dependency, no external APIs, no vendor
   lock-in. (This is why the Tailwind/Google-Fonts CDN design references are visual-only;
   the app uses vanilla, self-hosted assets.)
2. **No-LLM by default** — the core pipeline is deterministic and offline. Optional
   *local* models are acceptable later, but never the default experience.
3. **OCR quality is the product** — quality matters more than adding more file formats.
   Preprocessing and verification are **core capabilities, not extras**.
4. **Human-in-the-loop** — human review/correction is expected and designed for.
5. **Bangladesh focus** — mixed Bangla + English is the primary case.

## Architecture principles

- Keep converters **pure and tier-agnostic**; business logic must not live inside OCR
  engines.
- Feature segmentation (any future Basic/Advanced split) lives at the **UI/API layer**, so
  future monetization never requires an engine rewrite.
- Everything stays **benchmarkable and reproducible**.

## Future packaging (planning only — NOT to implement now)

No payments, subscriptions, accounts, authentication, or enterprise features. The app stays
offline and self-hosted. Keep extensibility in mind only. The eventual (not-yet-built)
split is captured in [`product-tiering.md`](product-tiering.md):

- **Basic mode:** PDF/Image/DOCX/Excel-CSV OCR, Markdown + ZIP export, verify view,
  statistics, batch, automatic preprocessing, TOC, presets.
- **Advanced mode:** Searchable PDF, Chunked JSON, knowledge-base export, OCR confidence
  scoring, low-confidence highlighting, editable verification, advanced analytics, manual
  preprocessing controls.

A **display-only Free/Advanced toggle** already exists in the UI (shows/hides Advanced
controls); it is *not* gating, auth, or payment.

## Development priority

**Highest:** OCR quality · verification workflow · Searchable PDF · Chunked JSON ·
confidence scoring · **editable verification** · knowledge-base export.

**Lower:** more file formats · authentication · Docker polish · URL scraping ·
LLM-dependent features.

## Implication for current backlog

The remaining Tier-1 item — **editable verification / human-correction workflow**
(see `tier1.md`) — is now a *highest-priority* item, because human-in-the-loop correction
is central to the vision, not an optional extra. The OCR-accuracy eval harness
(`overallplan.md`) also remains a prerequisite for any "OCR quality is the product" claim.
