# 2026-08-24 — Fast Loop v1 P0.1: brand-kit asset previews (`view("asset:…")`)

Spec: `subsystems/clue-design/docs/deepagent-fast-loop-v1-spec.md` §4 P0.1.
Forensics: `_memory/2026-08-24-deepagent-fast-loop-session.md`.
Base: `59b55793` (branch `integration/frontend-design-part-iv-v4`).

## Root cause — confirmed, and one layer deeper than the spec stated

The spec named one defect; the live run needed **two** fixed to deliver a pixel.

1. **Path shape (the named defect).** `LumenDesignTools._asset_preview_path`
   (`apps/agent_runtime/lumen_agent/tools/substrate.py`) appended the record's
   `media.…location.opaque_ref` verbatim onto `effective_asset_store_root`. The API
   points that root at the per-WORKSPACE engine cache
   (`api_engine_cache_root(workspace_id)` = `<root>/ws_X`), so a D4 durable ref
   `ws_X/design/<digest>` resolved to `<cache>/ws_X/ws_X/design/<digest>` — a doubled
   workspace segment that never exists. Every `view("asset:…")` on a brand-kit asset
   answered `asset_missing_file`, and the author placed imagery blind.

2. **No read-through (found while fixing 1).** `brand_kit_asset_manifest` handed the
   records over with no `ensure_materialized`, unlike its two siblings
   (`brand_kit_font_spec` for faces, `reference_asset_manifest` for attachment
   previews). Durable bytes live at `.artifacts/ws_X/design/<digest>`; the engine cache
   is transient and per-machine. It only *looked* healthy in dev because the same
   process had ingested the assets. A fleet worker, or any wiped cache, gets a manifest
   with no pixels behind it even after fix 1.

## Fix

- `_asset_preview_path` resolves **by digest** — `clue_design.storage.location_digest`
  (the canonical "resolve by digest, never by path" helper, which knows all three
  historical ref shapes) plus `blob_path_for_digest` (the one place the engine-cache
  layout is spelled out). Primary media prefers `media.digest.value`, falling back to
  the location. No string concatenation of a stored ref anywhere.
- `brand_kit_asset_manifest(repo, brand_kit, blobs, cache_dir)` now runs the D4
  read-through over `record_digests(...)` of every manifest entry. Both call sites
  (`load_brand_kit_by_value`, `resolve_web_turn_brand_kit`) hoist one `cache_dir` and
  share it with the font spec.

Legacy `sha256/<ab>/<digest>` refs keep working — pinned by a test.

## Tests (the gap that let this ship)

Existing coverage was ordinary design previews + unknown asset ids only.

- `apps/api/tests/test_asset_custody.py::test_view_asset_delivers_pixels_for_a_durably_stored_kit_asset`
  — the end-to-end one: real upload → durable custody → **wipe the workspace cache** →
  `load_brand_kit_by_value` → assert both digests are back in the cache → real
  `LumenDesignTools` (unstubbed engine) → `view("asset:<id>")` → decodable pixels.
  Red-proofed against BOTH halves independently (revert the resolver → the exact
  production `asset_missing_file` string; revert the read-through → cache assertion).
- `apps/agent_runtime/tests/test_deepagent_harness.py` — two DB-free guards so the
  runtime suite alone catches a regression: a genuine `clue-storage` record (ref minted
  by `design_storage_key`/`design_location`, not typed out) delivering exact thumbnail
  bytes, and the legacy engine-cache ref shape still resolving.

Commands (design subsystem's own toolchain; full suite NOT run — >1h):
```
cd subsystems/clue-design
CLUE_DATABASE_URL=... PYTHONPATH=.:apps/api:apps/agent_runtime <venv>/bin/python -m pytest \
  apps/agent_runtime/tests/test_deepagent_harness.py \
  apps/api/tests/test_asset_custody.py \
  apps/api/tests/test_brand_pin_brief.py
```
→ 63 passed. Plus `test_brand_fidelity.py`, `test_brand_card.py`,
`test_view_and_finalize_hygiene.py`, and
`test_api.py::test_resolve_agent_turn_brand_kit_passes_document_kit_by_value` → green.

## Residuals / follow-ups

- **`subsystems/clue-design/apps/agent_runtime/lumen_pipeline_archive/tools.py:1218`
  carries the identical bug.** Deliberately untouched — the archive is frozen and R1
  quarantined; noting it so it is not rediscovered.
- **Behaviour change, fail-safe direction:** a thumbnail whose `location.provider` is
  outside `STORED_LOCATION_PROVIDERS` no longer resolves (it used to concatenate). The
  resolver now falls through to the primary media, then to `None`. An unknown
  provider's ref was never a path we own.
- `account_assets` (P5 personalization logos) get no read-through — they are not a
  `view("asset:…")` target today, so it is out of P0.1's scope. If that target is ever
  widened, mirror the manifest change.
- Off-request `api_engine_cache_root` re-derives from settings, not `app.state`, so a
  test injecting a cache root into `create_app` must also point
  `settings.lumen_asset_store_root` at it (the new API test does; recorded because it
  is a real footgun for the next suite that drives an off-request resolver).
