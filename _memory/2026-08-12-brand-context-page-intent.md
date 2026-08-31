# 2026-08-12 — Founder intent: the Brand Context page (pre-slice-3 briefing)

Founder briefing delivered before slice-3 implementation start (transcript + screenshot in
`.context/attachments/`). **Not in current scope — no implementation now.** Recorded so slice-3
decisions stay compatible with it.

## What the founder described

A **Brand Context** section in the platform where the client sees everything we store about
their brand. Shape (per the sample screenshot, a brand-kit-editor mock):

- Left nav section "Brand context" with two groups:
  - **Brand kit** — Colors, Typography, Assets (the design-subsystem ingestion output; stays
    dummy on this branch per standing ruling).
  - **Knowledge** — a folder tree of markdown docs: Company (e.g. `Overview.md`), Product,
    Audience, Proof, **Memory**.
- The knowledge docs render as an **uneditable Markdown preview**. The user cannot free-text
  edit. Editing model: select/highlight lines (Codex/ChatGPT-annotation style) → attach a
  comment → on "send," **an agent handles all annotations and reframes the content**.
- Content is NOT one doc per company — it spans market position, reviews, competitors, all
  products in detail, per-product value proposition, mission statement, brand voice / style
  guide, etc.
- Screenshot is a sample/idea, not final design.

## Why it matters for slice 3 (and later)

1. **This page is the eventual read surface for recon's client KB.** The knowledge tree
   (Company / Product / Audience / Proof) maps almost 1:1 onto the ratified D-6 checklist
   groups (product & value / pricing & proof / customers & market / competitors & buyers).
   Slice 3's per-field events, the `client.competitor` + buyer fields, and the LLM claim
   extractor produce exactly the raw material these docs will project.
2. **Docs are projections of claims, not stored free text.** The uneditable-preview +
   annotate-via-agent model fits the architecture's core bet: facts stay typed claims with
   provenance; the page renders a markdown projection; user corrections flow through an agent
   (which can update/supersede claims or record preferences) rather than mutating prose.
   Annotation-comments smell like Doc M scoped-memory material (advisory preferences) and/or
   claim corrections — the two species must not mix.
3. The "Memory" folder in the Knowledge tree is presumably the Doc M scoped-memory surface
   made visible.
4. No frontend contract exists for this page yet; when it's specced, it follows the branch
   charter (contract-gap review, repository seam, fixtures first).

## Status

Informational only. Slice 3 proceeds unchanged; keep extractor output claim-shaped and
group-mappable so the future Brand Context projection needs no rework.
