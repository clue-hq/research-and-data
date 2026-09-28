# 2026-09-02 — WOFF2 brand fonts: investigation + option A plan (not yet executed)

Follows the rung-A durability finding (`_memory/2026-09-02-scene-streaming-rung-a.md`): the P0.4
mid-run checkpoint never fired for WOFF2 brands because the SVG export refused to embed them.

## Findings (all verified on the colombo box, 2026-09-02)
- The refusal is the CONTAINER check, not the license check. `lumen-skia/src/embed.rs::parse_fs_type`
  reads OS/2 fsType from raw sfnt only; WOFF2 fails before any license bit is read. Live probe via
  the release helper on the Apollo scene: PNG shapes Season Mix (CoreText parses WOFF2 on macOS);
  SVG fails `export.font_embed_unsupported_container`.
- Stored fonts on this box: 189 files on disk — 178 woff2 / 9 otf / 1 ttf / 1 woff. Of the ten sfnt
  files, none carry a restricted fsType bit. DB rows: 367 woff2 / 136 ttf / 12 otf / 2 woff across
  47 workspaces. The license gate has never blocked a stored font; the wrapper blocks 94%.
- Three consumers only read sfnt: the SVG embedder/subsetter (Rust), CanvasKit in the browser
  (`loadCanvasKit.ts` says it cannot read woff2; kit faces are fetched raw by asset id), and
  FreeType on Linux (our skia-safe build has no `freetype-woff2` feature — production parity risk;
  macOS works only via CoreText).
- Ingestion already ruled the consent question the founder raised (D-F2, `normalizer/emit.py`):
  workspace-brand fonts are `embeddable: true, basis: platform-terms`. The Apollo kit predates it
  (`embeddable: false`), so its WEBSITE export excludes both families today — separate backfill.
- Rust `AssetRecord` serde drops unknown fields, so a "derived sfnt blob" pointer on the record
  would be stripped on any helper round-trip → chose primary-bytes-sfnt over a two-blob pointer.
- `brotli` (needed by fontTools for WOFF2) is installed in `.venv` but NOT in `uv.lock`.
- Every font byte enters through `CoreClient.ingest_asset` (harvest, uploads, PDF, `POST /assets`,
  font library). The helper refuses a declared MIME that contradicts sniffed bytes, so the decode
  must rewrite the MIME too.

## Founder rulings
- Proceed with option A (decode once at ingestion; web lane keeps WOFF2). Fable's refinement:
  primary bytes become sfnt, web export re-encodes to WOFF2 deterministically (R1–R4 in the plan).
- fsType license gate removal: advised against (foundry terms ≠ user consent; gate blocks nothing);
  left as an open ruling.

## Plan
`docs/superpowers/plans/2026-09-02-woff2-font-decode-at-ingestion.md` — 7 tasks: helpers +
brotli dep; chokepoint in `CoreClient.ingest_asset`; pipeline/upload proof; engine red/green pin;
web-lane re-encode; backfill script (`scripts/decode_stored_web_fonts.py`, dry-run default);
close-out (apply on dev, live proof, memory, CLAUDE.md bullet, Task 4b excuse removal condition).
Execution rules: Opus-only implementers, Fable reviews/verifies/decides.

## Not done yet
- No code written. Backfill not run anywhere. Task 4b marker excuse stays until every env is
  backfilled.
