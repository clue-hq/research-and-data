# Phase 3b Browser E2E — Image Edit Before/After Gate

**Branch:** `agents/editing-roundtrip-v0`  **HEAD:** `2b8f6ab3c395` (feat(image-edit): 3b — prompt image edit + remove-bg with Before/After accept gate)
**Date:** 2026-07-05
**Driver:** real browser via Playwright MCP against the live stack (WASM editor, CanvasKit canvas, FastAPI backend).

## Stack under test

- Engine handshake: browser WASM `2b8f6ab3c395` == API helper `2b8f6ab3c395` == git HEAD. `/build-info` reports `engine_commit: 2b8f6ab3c395`. Editor NOT in server-only mode (no banner; canvas selectable/editable).
- Served WASM sha256 == local WASM sha256 (`f08c48d8…a75305`) — frontend serves the current artifact.
- **Real model calls are impossible (OpenRouter monthly cap → 403).** All image generation/editing was routed through a committed stdlib-only mock: `apps/api/tests/fixtures/mock_image_model.py`, on `http://127.0.0.1:8799`, wired to the backend process ONLY via `IMAGE_MODEL_BASE_URL` / `IMAGE_MODEL_API_KEY=mock` / `IMAGE_MODEL_ID=mock-image-v1` (no `.env` edits).
- Provider id `image-gen-v1` (the editor default) routes through the Python T2I/edit path → the mock.

### Mock behaviour (deterministic, PIL-free PNG via zlib/struct)
- **Plain generation** (`content` is a bare string): opaque solid 512×512 RGB PNG, hue derived from prompt hash. The word "background" in a generation prompt does NOT force transparency (only the edit path honours the bg-removal heuristic) — so "…clean studio background" still renders opaque.
- **Edit** (`content` is a list: image_url part(s) then a text part): hue derived from the *instruction* hash → Before ≠ After visibly. If the instruction mentions background/transparent/remove-bg (or the body hints transparency), returns an **RGBA** PNG with a genuine transparent centre disc so remove-bg is distinguishable.
- Response shape: `{"choices":[{"message":{"images":[{"image_url":{"url":"data:image/png;base64,…"}}]}}]}`.

## Verdict table

| # | Step | Result | Evidence |
|---|------|--------|----------|
| 1 | Generate an image INTO a node via the inspector Generate flow; renders on canvas | **PASS** | Prompt "solid teal product hero, minimal studio" → `POST /assets/generate` (provider `image-gen-v1`) → asset `asset_gen_9319cac745a0` (raster_image, ready, image/png) placed on `node_hero_image`; opaque solid renders on canvas. `01-image-generated-on-canvas.png` |
| 2 | Select image node → Edit affordance + "Remove background" appear (only for a ready image asset) | **PASS** | With a ready asset, inspector shows the "Edit image" instruction box (`image-edit`), `Edit` submit (`image-edit-submit`), and `Remove background` (`image-remove-bg`), gated by `canEdit`. `02-edit-affordance-and-remove-bg.png` |
| 3 | Type instruction → Edit → pending → Before/After panel with two distinct thumbnails | **PASS** | "make it sunset orange and warmer" → candidate `asset_gen_fe37f87a62b7`; `image-edit-review` panel shows Before=`asset_gen_9319cac745a0`, After=`asset_gen_fe37f87a62b7`; the two thumbnails are visibly different colours (olive vs pale-green+purple stripe). Node asset_id unchanged (no auto-swap). `03-before-after-panel.png` |
| 4 | REJECT → panel clears, scene untouched (asset_id unchanged) | **PASS** | After `image-edit-reject`: review panel gone; `node.kind.asset_id` still `asset_gen_9319cac745a0`; placement/alt unchanged; scene asset count unchanged. `04-reject-panel-cleared-scene-untouched.png` |
| 5 | Same-instruction edit hits the server cache → ACCEPT swaps asset_id (fit/focal/alt preserved) → ONE ⌘Z restores previous → redo re-applies | **PASS** | Re-edit with identical instruction returned the SAME candidate `asset_gen_fe37f87a62b7`; response body `"deduplicated": true`; backend log `{"asset_id":"asset_gen_fe37f87a62b7","cached":true,"deduplicated":true,…}` (10.4 ms vs ~986 ms for the uncached first edit). ACCEPT → node asset_id swaps `9319cac745a0`→`fe37f87a62b7`; fit=cover, focal={0.5,0.5}, alt="solid teal product hero, minimal studio" all preserved. One `⌘Z` → asset_id back to `9319cac745a0`; `⌘⇧Z` → back to `fe37f87a62b7`. `05a-accepted-swap.png`, `05b-undo-redo-verified.png` |
| 6 | Remove background → candidate → SAVE AS NEW → scene unchanged, status-line confirmation, new asset in library | **PASS** | Remove background → candidate `asset_gen_6b6a8881a6c5` with `raster.has_alpha == true` (RGBA). SAVE AS NEW: node asset_id **unchanged** (`asset_gen_fe37f87a62b7`); status line `data-status="saved"` reads "Saved Remove the background completely to the asset library."; `GET /assets` includes the new asset, and it appears in the Asset library panel on refresh (search "Remove the background" → one item labelled "Remove the background completely"). `06a-remove-bg-candidate.png`, `06b-save-as-new-in-library.png` |
| 7 | Reload → the accepted asset from step 5 persists on the node | **PASS** | Full page reload of the document → `node_hero_image.kind.asset_id == asset_gen_fe37f87a62b7` (the accepted edit), placement/alt intact, editor not in server-only mode. `07-reload-accepted-asset-persists.png` |
| 8 | `GET /assets/{id}` → source.kind == "edited", source_asset_id chains to the original | **PASS** | `asset_gen_9319cac745a0`: `source.kind == "generated"`. `asset_gen_fe37f87a62b7`: `source.kind == "edited"`, `source_asset_id == "asset_gen_9319cac745a0"`, has_alpha=false. `asset_gen_6b6a8881a6c5`: `source.kind == "edited"`, `source_asset_id == "asset_gen_fe37f87a62b7"`, has_alpha=true. Clean two-level chain generated → edited → edited. |

**Score: 8/8 PASS.**

## Console

Throughout the session the console accumulated **188 error entries, ALL identical**:

> `[ERROR] Unable to preventDefault inside passive event listener invocation. @ …/react-dom-client.development.js`

Zero of these originate from the Phase 3b product code. This is a known React-DOM **dev-mode** artifact emitted by CanvasKit's passive wheel/pointer listeners on the product canvas; it fires on canvas interaction/zoom and is unrelated to image edit. No network failures, no uncaught exceptions, no product errors. Full dump: `console-errors-all.txt`.

**Verdict on the "console must stay free of errors" gate:** the console is NOT strictly empty, but the only entries are this single library-level dev-server warning (see Bug B-1 below). No product error appeared at any step.

## Bugs / observations found (NOT fixed — recorded per instructions)

- **B-1 (pre-existing, low, dev-only): CanvasKit passive-listener console spam.** Every canvas wheel/pointer interaction logs `Unable to preventDefault inside passive event listener invocation` at ERROR level (React-DOM dev build). 188 occurrences in this run, all identical. Not triggered by the 3b flow specifically; it is canvas-wide. Cosmetic in dev; would not appear in a production React build (the debug hook and this warning path are dev-only). Recommend either registering the wheel listener as non-passive or downgrading expectation for "clean console" on the CanvasKit surface.

- **B-2 (minor, UX): "Save as new" does not refresh the Asset library panel.** After SAVE AS NEW the new asset is persisted (confirmed via `GET /assets`) and the status line confirms it, but the always-mounted Asset library list does not re-fetch, so the new thumbnail does not appear until the panel is otherwise refreshed (e.g. typing in its search box or changing the kind filter, both of which re-fetch). The asset IS there — this is a stale-view issue, not data loss. Matches the code path noted in `ImageInspectorSection` (`saveCandidateAsNew` sets a notice and clears the candidate but emits no library-refresh signal).

- **Observation (not a bug): scene-local asset registry grows to 2 after an edit review.** After an edit produces a candidate, the scene's local `assets` map holds both the current and candidate records even after Reject/Save-as-new; the node's *placement* is the source of truth for what renders, so the design is visually unchanged. This is expected (the candidate thumbnail is previewed via an upserted scene asset).

## Notes on test seeding

The empty document has no image node to select, and the inspector Generate flow requires an image-kind node. The node was seeded through the exact editor operation pipeline the product uses — `window.__lumenEditorDebug.applyOperations([{ kind:"insert_node", … kind:{kind:"image", asset_id:""} …}])` — which persists the batch to the backend (verified: `operation_batch_applied` in the backend log, and the node survived reload in step 7). Everything after seeding (generate, edit, accept, reject, remove-bg, save) went through real UI clicks on the real inspector controls.

## Artifacts

- `01-image-generated-on-canvas.png` — step 1 (also shows the step-2 Edit/Remove-bg affordance in the inspector)
- `01a-generate-flow-ready.png` — the Generate flow before submit
- `02-edit-affordance-and-remove-bg.png` — step 2 affordance
- `03-before-after-panel.png` — step 3 Before/After (visibly distinct)
- `04-reject-panel-cleared-scene-untouched.png` — step 4
- `05a-accepted-swap.png`, `05b-undo-redo-verified.png` — step 5
- `06a-remove-bg-candidate.png`, `06b-save-as-new-in-library.png` — step 6
- `07-reload-accepted-asset-persists.png` — step 7
- `console-errors-all.txt` — full console error dump
- `../../../apps/api/tests/fixtures/mock_image_model.py` — the committed mock image model
