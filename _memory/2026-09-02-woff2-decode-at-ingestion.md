# 2026-09-02 — WOFF2 fonts decoded at ingestion (option A)

## What changed
- `lumen_api/font_containers.py`: lossless WOFF/WOFF2 <-> sfnt (deterministic; brotli now declared).
- `CoreClient.ingest_asset` decodes web fonts before the Rust helper (MIME/filename/provenance rewritten; undecodable → `ingest.font_decode_failed`).
- `web_export._gather_fonts` re-encodes stored sfnt to WOFF2 (zip + hosted `/asset-store/{digest}`), content-addressed.
- `scripts/decode_stored_web_fonts.py` backfill; applied on colombo dev: `applied: 294 decoded, 0 relabelled, 0 skipped, 142 missing blobs, 0 failed` (exit 1 by design, because `missing` is non-zero). Font rows before → after: `font/woff2` 434 → 141, `font/woff` 2 → 1, `font/ttf` 188 → 474, `font/otf` 12 → 20.

## Why
367 of the 517 stored brand faces were WOFF2 at investigation time — 94% of the font FILES on disk. Three consumers read only sfnt: the Rust SVG embedder/subsetter (`lumen-skia/src/embed.rs::parse_fs_type`), CanvasKit in the browser, and FreeType on Linux (skia-safe is built without `freetype-woff2`, so macOS worked only via CoreText). Storing the sfnt as the asset's PRIMARY bytes beat a two-blob pointer (sfnt alongside the original web container) because the Rust `AssetRecord` drops unknown fields on any helper round-trip, so a pointer written onto the record would be silently stripped.

## Verified
- Focused suites: `test_font_containers`, `test_core_ingest_font_normalization`, `test_ingestion_font_decode`, `test_export_decoded_web_font`, `test_web_export`, `test_decode_stored_web_fonts` — 51 passed / 51 in one run. Full `apps/api/tests` gate, run the way the D4 close-out ran it — on a fresh throwaway database (`clue_woff2_gate`, migrated to head `f506a1210f0c`), so the shared DSN's stale rows and its live design API could not interfere: 30 failed of ~1,560 collected, and every one is pre-existing. Evidence: the same 30 minus the stale-digest and stolen-job families (21) that only exist on the shared DSN; of the 30, the custom-component families are compile-worker `503`/`transient_error`, the `test_api` w14/w17 tests hit the live image API, and the remaining nine fail identically at the plan's base commit `2e68ef87b` in a separate worktree against the same fresh DB (grammar-audit poll timeouts, web-turn "Agent runtime failed", custom-component compile gate). The one test that differed (`test_ingestion_routes` force-render) passed at HEAD on rerun — the 60 s job-poll flake. No failure touches a font path.
- Runtime tests for the Task 4b comment-only edit: `6 passed, 1554 deselected`.
- Live, through the restarted colombo design API: `GET /assets/asset_ing_03046b53ca110eaf/bytes` returns `font/ttf`, 345,584 bytes, sfnt magic. `POST /documents/doc_1c35a98d45435c7bb8d19408bb9e03e8/export {"format":"svg"}` returns status ok with zero font diagnostics and `@font-face` rules for both "seasonMix" and "soehne" as `font/ttf` data URIs — the identical canonical-export path the design agent runs each round, which previously refused with `export.font_embed_unsupported_container`.
- Live, in the browser (edit mode): the Apollo LinkedIn ad renders its headline in Season Mix and its button in Söhne; the browser fetched both faces as decoded TTF; no kit-font diagnostics.

## Follow-ups
- Run the backfill on every other environment (istanbul/nashville worktrees' DBs, staging) before deleting the Task 4b checkpoint excuse (`render.py` / `substrate.py`). That string-keyed excuse stays until every environment is backfilled.
- Rows reported `missing` on this box: 142; they are blobs held by other worktrees' `.artifacts` roots plus `ws_test_*` leftovers, and were left exactly as they were.
- Rulings still open: fsType license gate (R4), pre-D-F2 kits' `license.embeddable=false` backfill.
- Test-DB hygiene (pre-existing, founder's open ruling): the shared test database accumulates `ws_test_*` `artifact` rows forever, which makes the cross-tenant `/asset-store/{digest}` route 404 in tests for any re-used digest (it scans the 50 oldest rows); and a design API running on the same DSN claims offered ingestion jobs from tests.
