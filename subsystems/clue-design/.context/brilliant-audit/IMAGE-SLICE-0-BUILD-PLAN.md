# Image Slice 0 — Build-Ready Implementation Plan

Sequenced, dependency-ordered, each step independently shippable with a test gate.
Companion to `IMAGE-MODEL-SLICE-0-AND-1-SPEC.md`. Branch: image-model line
(`add-image-model-to-design-tool`, based on the merged design-quality work).

## Test-command reference (the gates)
- **Rust assets:** `cargo test -p lumen-assets` (tests: `providers_contract.rs`, `qr_provider.rs`, `store_and_ingest.rs`, `processing.rs`)
- **Rust core:** `cargo test -p lumen-core` (assets/brand/layout/dsl tests)
- **Helper rebuild (for e2e + editor wasm):** `cargo build -p lumen-api-helper` ; editor: `pnpm -C apps/editor build:wasm`
- **Agent runtime:** `PYTHONPATH=apps/api:apps/agent_runtime <venv> -m pytest apps/agent_runtime/tests/test_lumen_deepagent_runtime.py`
- **API:** `<venv> -m pytest apps/api/tests/test_api.py apps/api/tests/test_phase_g_conformance.py`
- **Editor:** `pnpm -C apps/editor test` (vitest; `pretest` builds wasm)
- **Catalog/DSL validator:** `.context/p02-validate.py` / `p02-revalidate-all.py`
- **Render probe:** `.context/render-probe.py` (DSL→PNG)
- venv: `/Users/aryankeshri/Documents/brilliant-design/.venv/bin/python`; `LUMEN_CORE_HELPER=$PWD/target/debug/lumen-api-helper`

## Pre-flight decision (settle before Step 1)
**Where the T2I network call lives.** The existing `/assets/generate` route (`main.py:1953`) delegates to `core.generate_asset(provider=…)` → the **Rust** `ProviderRegistry` (`providers.rs:293 with_default_providers`, registered in `main.rs:1179`). Two options:
- **(Recommended) Python provider** — do the HTTP + retries + cache in the async API layer; feed bytes through the existing `core.ingest_asset(...)` (which already accepts `kind`/`license`/`provenance`/`source`, `core.py:137-172`) stamped `Generated`. Avoids adding `reqwest`/`tokio` to the sync `lumen-assets` crate; keeps tests offline. **Deviation C.**
- (Alt) Rust provider via a *sync* HTTP client (`ureq`, no tokio) registered in `with_default_providers`, env-gated so offline tests keep the stub.

Plan below assumes the **Python provider**, exposed under the same `/assets/generate` surface (provider id `image-gen-v1`), so the agent tool + editor share one endpoint.

---

## Step 1 — Real raster T2I provider [G0] · API/Python · M
**Files:**
- NEW `apps/api/lumen_api/image_provider.py` — `httpx` call to the hosted T2I API; map `{prompt, width, height, brand_notes, aspect_ratio}`→API params; return `{bytes, mime, provenance, license}`. Env config: `IMAGE_MODEL_API_KEY`, `IMAGE_MODEL_BASE_URL`, `IMAGE_MODEL_ID`, version pin; bounded timeout + retry.
- `apps/api/lumen_api/main.py:1953-1995` (`generate_asset` route) — branch: if `payload.provider == "image-gen-v1"`, call `image_provider.generate(...)` then `core.ingest_asset(bytes_base64=…, kind="raster_image", source={"Generated":{"model":…}}, license=…, provenance=…)`; else keep delegating to Rust (qr/stub).
- `apps/api/lumen_api/core.py` — confirm `ingest_asset` passes `source`/`license`/`provenance` through (it does, `:137-172`).

**Change:** wire one real model behind `image-gen-v1`; bytes land in the content-addressed store exactly like uploads, stamped Generated. No Rust change; no scene-schema change.
**Test gate:** `pytest apps/api/tests/test_api.py` green (add a test that POST `/assets/generate {provider:"image-gen-v1"}` with a **mocked** `image_provider.generate` persists a `raster_image` asset with `Generated` source + returns `asset_id` + bytes resolvable at `GET /assets/{id}/bytes`). Stub provider path stays green.

## Step 2 — Editor canvas renders real pixels [E0.1] · Editor · M
**Files:**
- `apps/editor/src/engine/renderAdapter.ts` — image branch (`:134 image?` field, `:232`, `:467`, `:540`): populate `descriptor.image` with a bytes/thumbnail URL (`assetBytesUrl`/`assetThumbnailUrl` from `engine/assetLibrary.ts:97-103`) + `fit` + `focal_point` from `node.asset_placement`.
- `apps/editor/src/engine/drawDescriptors.ts` — CanvasKit draw: decode via `MakeImageFromEncoded`, draw into the node box honoring **fit (cover/contain/crop) + focal_point + clip + corner-radius**, reusing the export crop math (mirror `crates/lumen-export/src/svg.rs focal_crop_geometry` / `lumen-skia render.rs:441-523`). Konva path: a `Konva.Image` equivalent.
- `apps/editor/src/engine/renderDiagnostics.ts:128-135` — drop/relax `EDITOR_RENDER_IMAGE_PLACEHOLDER` once bytes draw (keep `ASSET_MISSING`).

**Change:** the single biggest usability blocker — placed/generated images become visible in-editor, identical to export.
**Test gate:** `pnpm -C apps/editor test` — add a render test: a scene with a ready image node produces an image draw-op (not a placeholder) with correct fit/focal geometry. Manual smoke: load a fixture scene with an image → see pixels, cover-cropped to the frame.

## Step 3 — `generate_image` + `place_asset_in_node` agent tools [A0.2/A0.3] · Agent · M
**Files:**
- `apps/agent_runtime/lumen_deepagent/tools.py` — add `generate_image(...)` mirroring `generate_qr` (`:423-503`): build the generate request (`provider="image-gen-v1"`, prompt, `target_node_id`, constraints incl. **aspect derived from the target node geometry**), call the generate surface, `upsert_asset` (`:470`), return `asset_id`+provenance. Add `place_asset_in_node(node_id, fit="cover", focal_point, alt)` + `place_asset_in_slot(...)` wrapping the reversible Place ops.
- `apps/agent_runtime/lumen_deepagent/factory.py:37-42` — register `tools.generate_image`, `tools.place_asset_in_node`, `tools.place_asset_in_slot` in the `tools=[...]` list.

**Change:** the agent can generate a brand-conditioned image and place it cover-fit into a target, aspect matched to the frame.
**Test gate:** `pytest test_lumen_deepagent_runtime.py` — add tests (FakeCoreClient returns a ready asset): `generate_image` emits `upsert_asset` + returns id; `place_asset_in_node` emits a reversible `place_asset_in_node` op carrying fit/focal/alt; aspect is taken from node bounds.

## Step 4 — DECIDE rule + prompt-craft + scrim recipe; soften clause H [A0.1/A0.5/A0.6] · Knowledge/Agent · S
**Files:**
- NEW `apps/agent_runtime/knowledge_docs/knowledge/images/{decide,prompts,placement}.md` — Brilliant's decision table (photo→`generate_image`; icon/flat→library; abstract→shapes); 5-component prompt craft (Subject+Medium+Composition+Lighting+Quality, no in-image text, brand tone via `brand_notes`); per-use-case templates; the scrim idiom (`Frame{clip,rd} > Image{cover,focal}` + sibling `opacity.scrim` rect).
- `apps/agent_runtime/lumen_deepagent/knowledge.py` — add the `images/*` paths to PRIMARY + pin in `mandatory_task_paths` + `FULL_DELIVERY_PATHS` (parallel the foundations wiring).
- `apps/agent_runtime/lumen_deepagent/prompts.py:203-206` (clause H) — soften: imagery is welcome when it serves the message; reject only *gratuitous*/cliché imagery. Add the scrim rule to the author prompt + create-design SKILL.

**Change:** the guardrail (generate only what you can't build) + how to prompt well + always-scrim-text-over-image; removes the anti-image bias.
**Test gate:** `pytest test_lumen_deepagent_runtime.py` — assert `images/decide` is pinned + full-delivered (mirror the foundations pin test). Doc lint: validator on any fenced DSL in the new docs (`p02-validate.py`).

## Step 5 — Editor image inspector + generate-into-node + regenerate/replace + status [E0.2–E0.5] · Editor · M
**Files:**
- `apps/editor/src/components/InspectorPanel.tsx` — add an **Image section** for image nodes: Fit dropdown (cover/contain/crop), focal x/y, editable **alt**; emit `place_asset_in_node`/`asset_placement` `NodePatch`. Add a **canvas focal-dot overlay** (draggable) reusing focal geometry.
- `apps/editor/src/components/AssetBrowserPanel.tsx` + NEW generate control — a prompt box bound to the selected node: POST `/assets/generate {provider:"image-gen-v1", target_node_id}` → `upsert_asset` + `place_asset_in_node` against the **same node id**; **Regenerate** (prompt prefilled) + **Replace** (library scoped to node) carrying the existing `AssetPlacement` forward (not `{}`). Fix `buildNodePlacementOperations` (`engine/assetLibrary.ts`) to accept/preserve a placement instead of always `{}`.
- Status: surface `AssetStatus` Pending→Ready→Failed on the target (spinner/skeleton + error w/ `LUMA*` diagnostics).

**Change:** a real human refine loop — generate, recrop via focal, regenerate, replace, edit alt, see progress — without delete-and-re-place.
**Test gate:** `pnpm -C apps/editor test` — inspector emits correct `asset_placement`/`place_asset_in_node` ops on fit/focal/alt change; regenerate/replace preserve node id + carry placement; status reflects asset state. Manual smoke through the full loop.

## Step 6 — Generation cache [A0.8] · API/Agent · M
**Files:**
- `apps/api/lumen_api/image_provider.py` (or a small `image_cache.py`) — cache key `(normalized_prompt, width, height, model, reference_ids)` → `asset_id`; check **before** calling the provider; on hit, re-`place` the cached asset.
**Change:** the quality loop re-requests the same hero across iterations; without the cache every iteration re-pays the model and the design churns its imagery. (Store dedup is byte-digest only, *after* the call — too late.)
**Test gate:** `pytest apps/api/tests/test_api.py` — two identical generate requests (mocked provider) call the provider **once**; second returns the cached `asset_id`.

## Step 7 — aspect_ratio / image_size / reference fields [G0.2] · Core+API · S
**Files:**
- `crates/lumen-core/src/assets.rs:351-357` (`AssetGenerationConstraints`) — add `aspect_ratio: Option<String>`, `image_size: Option<String>`, `reference_asset_ids: Vec<AssetId>` (serde-default → back-compat).
- `apps/api/lumen_api/image_provider.py` — translate `aspect_ratio`→w/h; pass `image_size` tier; pass references if supported.
**Change:** aspect matched to frame (no stretched images), role-appropriate resolution. (Reference-image *use* is Slice 1; the field lands now.)
**Test gate:** `cargo test -p lumen-core` (serde round-trip of the new fields, defaults preserved); `pytest test_api.py` (ratio→dimensions mapping).

## Step 8 — Icon/illustration library + `svg(icon:name)` lowering + `place_icon` + library UI [I0/G0.3/A0.4/E0.6] · Core+Agent+Editor · M
**Files:**
- NEW icon set asset (bundled) + a resolver; `crates/lumen-core/src/dsl.rs:338` (`SvgIcon{icon}`, parsed at `:2940-2952`, currently **not lowered → LUMD0703**): lower `svg(icon:name)` to one `VectorNode` per top-level shape (grouped), `$color.*`-recolorable.
- `apps/agent_runtime/lumen_deepagent/tools.py` — `place_icon(node_or_slot, icon_name)` tool; register in `factory.py`.
- `apps/editor/src/components/AssetBrowserPanel.tsx` — searchable icon category; "Place" lowers to `VectorNode`(s).
**Change:** the reliable vector-illustration/icon path (curated, recolorable) for enterprise decks — covers "illustrations" without betting v1 on a generative-vector model (Deviation D).
**Test gate:** `cargo test -p lumen-core` — `svg(icon:calendar)` lowers to VectorNode(s), no LUMD0703, recolor via token works. `pytest` — `place_icon` emits correct ops. Editor test — icon places + renders as vector.

## Step 9 — `imagery` critic axis + repair routing [A0.7/critic] · Agent · S–M
**Files:**
- `apps/agent_runtime/lumen_deepagent/schemas.py:14-24` (`CritiqueCategory`) — add `imagery` (alongside `asset_use`).
- `apps/agent_runtime/lumen_deepagent/prompts.py` (`VISUAL_REVIEWER_SYSTEM_PROMPT`) — add an **Imagery** rubric axis: is an image warranted; relevance to message; aspect/crop fit; **text-legibility-over-image / scrim adequacy**; resolution-vs-rendered-size (DPI); garbled in-image text; on-brand; placeholder-vs-real.
- `apps/agent_runtime/lumen_deepagent/loop.py` — map an `imagery` critique to `RepairClass.asset_tool` (`schemas.py:217`); route to regenerate-with-revised-prompt / recrop(focal) / add-scrim / replace / remove — **not** a geometry patch (mirror the P1.5#2a recompose-recipe injection pattern).
**Change:** the loop gates image quality and repairs images as images.
**Test gate:** `pytest test_lumen_deepagent_runtime.py` — an `imagery` critique routes to `asset_tool` repair (not layout/targeted); the repair instruction names regenerate/recrop/scrim. Mirror the existing `recompose_recipe_for_feedback` test style.

## Step 10 — Scrim helper + grammar docs + catalog block + fixtures [S0/G0.4] · Knowledge/Catalog · S
**Files:**
- `apps/agent_runtime/knowledge_docs/knowledge/lumen-dsl/{grammar,text}.md` — document image authoring (fit/focal/alt/slot/aspect) + the scrim idiom.
- `apps/agent_runtime/knowledge_docs/knowledge/design/blocks/patterns.md` — add an **image-bearing hero/poster** block: `Frame{clip,rd} > Image{cover,focal}` + scrim rect + headline slot; validate.
- Golden fixtures: image-bearing scene → `crates/lumen-export` SVG/Skia golden + `.context/render-probe.py` PNG.
**Change:** the agent assembles image designs from a vetted block; render parity locked.
**Test gate:** `.context/p02-revalidate-all.py` (catalog all ok, now incl. the image block); `cargo test -p lumen-export` (golden); render-probe shows the hero image + scrim + legible headline.

---

## Definition of done (Slice 0 e2e gate)
Rebuild helper + wasm, then run the quality loop on real prompts (social ad w/ hero photo; deck slide w/ icon row) to `.context/post-imageslice0-runs/`, `LUMEN_AGENT_PREVIEW_FORMAT=png`. **Accept when** (per spec §6): the agent decides imagery correctly; a generated photo renders as real pixels in editor == export, cover-fit + focal, scrimmed under legible text, aspect-matched; the cache prevents re-gen across iterations; a human can generate/recrop/regenerate/replace/alt with status; icons place reliably; the `imagery` critic gates and repairs; output is good enough to ship for day-to-day work. All suites green: `cargo test -p lumen-assets lumen-core lumen-export`, `pytest` (agent + api), `pnpm -C apps/editor test`, catalog 22/22.

## Suggested commit sequence (one per step, local)
1 provider · 2 editor-render · 3 agent-tools · 4 decide+prompt+scrim · 5 editor-inspector · 6 cache · 7 constraints · 8 icon-library · 9 critic · 10 docs+catalog+fixtures. Each step is independently shippable and gated; push when you ask.
