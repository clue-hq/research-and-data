# Phase E: Asset Runtime And Creative Tools — Spec And Implementation Plan

Date: 2026-06-12
Branch: `phase-e/asset-runtime-v0`

## Purpose

Phase E turns fixture-only asset handling into a production asset runtime:
real uploads, real bytes in previews and exports, deterministic generation
(QR codes first), processing/validation, and placement rules that survive
print. This is the phase that makes the critic loop honest — today it
evaluates placeholders, which hides roughly half the visual-quality problem —
and it is a hard prerequisite for Phase G, whose per-instance artifacts
(account logos, personalized QR codes) are asset-generation problems.

Roadmap references: gap analysis "Phase E: Asset Runtime And Creative
Tools" and "Assets And Imagery" improvement plan; deferred backlog branches
`api/asset-store-v0`, `api/asset-library-v0`, `assets/processing-v0`,
`assets/generation-v0`, `export/asset-resolution-v0`; Phase D roadmap
decision: QR generation is the first deterministic provider.

## Decisions (2026-06-12)

1. **QR codes are the first generation provider.** Deterministic (pure
   encode, no AI dependency), directly demanded by the ABM premise
   (per-account QR on physical mailers linking to personalized landing
   pages). Implemented in Rust with the `qrcode` crate, emitting SVG vector
   output with explicit error-correction level (default M, H for print),
   quiet zone (4 modules), and a minimum-physical-size diagnostic for print
   media (below ~20mm at the declared DPI → warning).
2. **Storage is a trait with a local adapter first.** Content-addressed
   keys (SHA-256 of bytes) under a local directory; the S3-compatible
   adapter is a follow-up behind the same trait. The API stores bytes
   exactly once (dedup by digest).
3. **Bytes never enter the Scene.** `AssetRecord` stays metadata + location
   ref; a byte resolver trait serves preview/export/editor. The core crate
   remains free of storage/HTTP knowledge (golden rule).
4. **Archive-first lifecycle integrates with Phase D.** Phase D shipped
   archive status and reference-checked hard delete; Phase E adds the byte
   lifecycle: hard delete removes bytes only when no record references the
   digest.
5. **Licensing is enforced at export, recorded at ingest.** Every upload or
   generation captures provenance/licensing; export preflight rejects
   print/publish exports for assets whose license forbids it, with a
   precise diagnostic.

## Scope

Build, in order:

1. **E1. Asset byte resolver** — `AssetByteResolver` trait in
   `lumen-export` (adapter side, not core); fixture resolver re-implemented
   on it; SVG/PNG export embeds real raster/vector bytes (data URIs for
   SVG, decoded pixels for PNG); missing-byte diagnostics.
2. **E2. Storage + upload API** — storage trait + local content-addressed
   adapter; `POST /assets` (multipart upload), `GET /assets/{id}/bytes`;
   MIME sniffing on ingest; size limits; digest dedup.
3. **E3. Processing** — image probing (dimensions, DPI, transparency) via
   the `image` crate; SVG sanitization (strip scripts/foreign objects/event
   handlers); thumbnail derivation; all results persisted onto
   `AssetRecord` metadata.
4. **E4. QR provider** — `generate_qr` helper action + API route + agent
   tool: URL/text → sanitized SVG asset with provenance
   `generated:qr`, EC level, module count, and print-size diagnostics.
   Deterministic: same input → same bytes → same digest.
5. **E5. Asset library API** — workspace-scoped list/search
   (`GET /assets?kind=&q=`), archive filter, reuse across documents;
   document attach uses existing `UpsertAsset`/`PlaceAsset*` operations.
6. **E6. Placement semantics** — fit modes (contain/cover), crop/focal
   point honored by exporters, aspect-ratio validation, logo safe-area
   rule, min-DPI-for-print preflight diagnostic.
7. **E7. Editor asset browser** — upload/select/replace UI consuming the
   library API; thumbnails; emits canonical `UpsertAsset` /
   `PlaceAssetInNode` / `PlaceAssetInSlot` (optionally via `/edits` for
   envelope history).
8. **E8. Generation/vectorization adapter contracts** — provider trait +
   request normalization into `AssetRecord` with provenance/licensing;
   QR is the first concrete provider; AI image/vectorization providers are
   wired as adapters with a stub implementation (real providers are config,
   not architecture).
9. **E9. Conformance** — export with real bytes vs fixture baseline;
   licensing rejection; QR determinism; archive/delete byte lifecycle;
   critic preview consuming real assets.

## Non-Goals

- AI image generation model integration beyond the adapter contract.
- Background removal / image editing tools.
- Font asset runtime (export/print-fidelity workstream).
- CDN/signed-URL serving (S3 adapter follow-up).
- Per-instance binding of generated assets (Phase G; E provides the
  generator G calls).

## Slices, Tests, Gates

Each slice lands green with tests; commit per slice.

- **E1** tests: SVG export embeds a real PNG data URI; missing bytes →
  diagnostic, not panic. Gate: critic preview path renders a real logo.
- **E2** tests: upload → digest key on disk; duplicate upload dedups; MIME
  mismatch rejected. Gate: round-trip upload→resolve→export.
- **E3** tests: probe fills width/height/dpi/transparency; hostile SVG
  sanitized (script/onload stripped); thumbnail generated.
- **E4** tests: determinism (digest-stable), EC levels, quiet zone present,
  print-size diagnostic fires below threshold; agent tool trace records
  provenance. Gate: a mailer fixture carries a scannable QR (manual scan
  check recorded in memory).
- **E5** tests: list/search/filter; archived assets excluded by default.
- **E6** tests: cover/contain/focal crop golden SVGs; low-DPI print
  diagnostic; logo safe-area warning.
- **E7** tests: Vitest for browser panel; placement emits canonical ops.
- **E8** tests: provider trait round-trip with stub; provenance/licensing
  captured.
- **E9**: full matrix (same commands as Phase D) + new conformance
  fixtures.

## Test Matrix

Same as Phase D (`cargo fmt/test/clippy/wasm`, API + agent pytest, editor
lint/test/build) plus `cargo test -p lumen-export --test asset_resolution`.
