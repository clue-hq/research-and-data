# Image Model + Imagery — Scope (engine → agent, Brilliant-faithful)

Generated 2026-06-18 via a 4-reader fan-out over our stack + Brilliant's image knowledge.
Branch: design-agent-quality-audit. Status: SCOPE only (no code written).

---

All key seams confirmed against source: `Paint` has no `Image` variant (scene.rs), `AssetGenerationConstraints` has only width/height (no aspect_ratio/imageSize/reference_ids), `lumen-assets` has no HTTP client, `factory.py` exposes `generate_qr` but no `generate_image`, and `CritiqueCategory` has `asset_use` but no `imagery`. The `generate_qr` tool docstring already references `place_asset_in_node/place_asset_in_slot` ops. Writing the scope now.

---

# Scope: Generative Imagery for Lumen

Goal: add a text-to-image model + real imagery to Lumen, faithful to Brilliant's approach, with heavy emphasis on the **agent-side** decide → prompt → generate → place → critique flow. Today Lumen designs contain zero imagery: the only generator is `StubImageProvider` (a solid-color PNG from `sha256(prompt)`), and the agent has no image tool, no decision rule, and no imagery critic.

## 1. What we already have (build on, don't reinvent)

The byte/runtime layer is surprisingly complete. The QR provider proves the **entire** generate → ingest → store → upsert → render → export loop end-to-end. Do not rebuild any of this:

- **Provider seam, end-to-end wired.** `AssetGenerationProvider` trait (`crates/lumen-assets/src/providers.rs:63-69`, synchronous `generate(&AssetGenerationRequest) -> ProviderArtifact`), `ProviderRegistry::with_default_providers()` dispatching by string id (`providers.rs:282-346`), the `generate_asset` CLI action (`crates/lumen-api-helper/src/main.rs:1169-1228`) which runs the provider then funnels bytes through the **same** ingest pipeline as uploads (sanitize/probe/store/record/thumbnail) and stamps `AssetSource::Generated{model}` + license/provenance. A real model drops in **behind this trait by id** — "configuration, not surgery."
- **Generation contract.** `AssetGenerationRequest{request_id, prompt, output_kind, target_node_id, target_slot_id, constraints}` + `AssetGenerationConstraints{width, height, mime_type, transparent_background, brand_notes}` (`crates/lumen-core/src/assets.rs:340-358`) — confirmed serde types. `brand_notes: Vec<String>` is a ready-made brand-conditioning hook.
- **First-class image node + placement.** `NodeKind::Image(ImageNode{asset_id, alt})` (`scene.rs:331,431-434`); `AssetPlacement{fit: ImageFitMode{Contain,Cover,Crop}, focal_point, preserve_transparency, alt_text}` on **every** node (`scene.rs:288-290`, `assets.rs:328-338`); `clip` + `CornerRadii` per node.
- **Production-grade render, parity-locked.** Cover/contain + focal-point crop + clip + corner radius implemented identically in SVG (`svg.rs:507-602`, shared `focal_crop_geometry` 1032-1086) and Skia/PNG (`render.rs:441-523`). A generated image **will appear in the preview the critic sees** with no render work.
- **Content-addressed store + export resolution.** `LocalAssetStore` (sha256 dedup, `store.rs`); `AssetByteResolver` trait + `StoreBackedResolver` wired into ExportPreview/derive (`store_resolver.rs`, `main.rs:886,1832`).
- **Validation + print checks.** Aspect-ratio tolerance 0.02 (LUMA0310), crop-needs-focal (LUMA0315), min-DPI, transparency (`assets.rs:780-859`); export license-block (LUME0212) + effective-print-DPI floor (LUME0213, `checks.rs:160`).
- **Brand tokens + scrim tokens.** `asset.illustration.primary`, `asset.texture.subtle`, `asset.icon.primary` are REQUIRED_PRODUCT_READY tokens (`brand.rs:158-166`); `opacity.scrim=0.56` / `opacity.overlay=0.88` exist (`brand.rs:153-154`).
- **Reserved-but-unwired scaffolding.** Rust: `AgentAssetRequest::{GenerateImage,GenerateSvg,VectorizeImage,PlaceAsset}`, `AssetTool` trait + `UnavailableAssetTool`, `VisualIssueCategory::Imagery` (`lumen-agent/src/lib.rs:936-985`). Python: `EditSurfaceRecommendation.asset_tool`, `RepairClass.asset_tool`, `CritiqueCategory.asset_use` (`schemas.py`), `recommend_edit_surface` already detects "generate image"/"vectorize" intents (`tools.py:1044-1102`). The taxonomy anticipates imagery; nothing fires it.
- **HTTP surface + DSL.** `POST /assets/generate` (`main.py:1953-2030`) + `CoreClient.generate_asset` (`core.py:199-218`) exist but are **not called from the agent's CoreClient**. DSL `img`/`image asset(id)` lowers to `NodeKind::Image` (`dsl.rs:2895-2920,3588`).
- **The reference template: `tools.generate_qr`** (`tools.py:423-503`) — calls core, ingests, upserts via `{kind: upsert_asset}`, returns asset_id. Its docstring already says "Place the returned asset with a `place_asset_in_node/place_asset_in_slot` operation." `generate_image` should mirror it exactly.

**Bottom line:** the plumbing is ready. The missing work is (1) one real T2I provider, (2) the agent brain (decide/prompt/place), (3) the imagery critic. Plus a few ergonomic engine items.

## 2. Scope by layer

### (a) Asset pipeline / image-model provider

| Work | Effort | Detail |
|---|---|---|
| Real T2I provider | **M** | New `AssetGenerationProvider` impl (e.g. `image-gen-v1`) calling a hosted T2I API. Map `request.prompt` + `constraints{width,height,mime,transparent_background,brand_notes}` → API params; decode returned bytes into `ProviderArtifact{bytes,mime,kind,license,provenance,metadata,diagnostics}`. Register by id in the helper's registry builder. **No core schema change.** |
| Where the network call lives | **M** (decide) | `lumen-assets` has **zero** http/async deps (`Cargo.toml:8` = `image`,`qrcode` only) and the helper is a sync one-shot subprocess. **Recommended:** make the network call in the **Python API layer** (already FastAPI/async) and feed raw bytes through existing `ingest_asset` — avoids adding `reqwest`/`tokio` to the sync Rust crate. Alternative: blocking `reqwest` inside the one-shot helper. Pick the Python path. |
| Config / credentials | **S** | Env-keyed registration (API key, base URL, model id, provider allowlist, version pin). Trait/registry already accept arbitrary providers. |
| Generation cache | **M** | Cache `(normalized_prompt, constraints, model, reference_ids)` → asset_id **before** calling the provider. Store dedups on byte digest only, *after* the (paid, non-deterministic) model runs; Brilliant-style loops re-request the same hero across iterations. |
| Async/job model | **M** (or S) | Calls take seconds-to-tens-of-seconds. Simplest: bounded synchronous timeout + retry (agent runs server-side, can wait). Defer a job/poll endpoint unless the editor needs interactive gen. |

### (b) Engine

| Work | Effort | Detail |
|---|---|---|
| Aspect/imageSize/reference fields | **S–M** | Add `aspect_ratio: Option<String>`, `image_size: Option<String>` (1K/2K/4K), `reference_asset_ids: Vec<AssetId>` to `AssetGenerationConstraints` (serde-default = back-compat). Translate ratio→w/h in the provider. Reference-image support is the M part (provider must accept image inputs). Mirrors Brilliant `imageSize`/`aspectRatio`/`referenceElementIds` (`integration.md:8-19,44-46`). |
| Scrim/overlay | **S** | **Composable today** — no new primitive. Scrim = sibling semi-transparent Rect/linear-gradient above the Image node, using existing `opacity.scrim`/`opacity.overlay` tokens. The real work is the agent recipe + critic rule, not engine. |
| `Paint::Image` variant (image-as-fill) | **L (optional)** | `Paint` is `{Solid, LinearGradient, RadialGradient, Token}` — **no Image variant** (confirmed `scene.rs:653-658`). Brilliant's canonical idiom is image-as-FILL (`f[(img(hero.png))]`) with scrim as a second fill. Adding `Paint::Image{asset_id, fit, focal}` touches Paint enum + DSL + scene + validation + **both** renderers + PDF degrade + golden fixtures. **Recommended for v0: do NOT build this.** Use the `Frame{clip,radius} > Image{fit:cover}` + sibling scrim idiom, which renders correctly today with zero core change. (See Deviation A.) |
| Intrinsic-aspect layout sizing | **M (defer)** | Images measure as `fixed_or_zero` box (`layout.rs:655`); no auto-height from asset ratio. Author must set both dims. Quality follow-up, not v0-blocking. |
| PDF image embedding | **M (defer)** | PDF drops images (`warn_unsupported`, `pdf.rs:286`); only DPI metadata validated. SVG/Skia placement math is reusable. Needed only if image designs export to print. |
| EffectFeature matrix entry | **S (defer)** | Add an `ImageFill`/`RasterImage` feature + per-target verdicts so PDF's drop surfaces through the central LUMX channel instead of ad-hoc warnings. Mechanical. |

### (c) DSL / grammar

| Work | Effort | Detail |
|---|---|---|
| Standalone image authoring | **none** | Works today: `img(id)` / `image asset(id)` lowers to `NodeKind::Image` (`dsl.rs:2895-2920`). Author wraps in `Frame{clip,radius}` and sets `fit:cover` + focal via placement op. |
| `img()` inside fill list | tied to L above | Only needed if `Paint::Image` is built. Skip for v0. |
| Fit/crop/focal/alt/slot attributes | **S** | Ensure DSL/placement exposes `fit`, `focal_point`, `alt`, `slot()` so the agent authors complete, validated placements. Placement ops (`PlaceAssetInNode{placement}`, `PlaceAssetInSlot{placement}`) already exist and are reversible (`operations.rs:168-182`). |

### (d) Agent loop + tools

| Work | Effort | Detail |
|---|---|---|
| `tools.generate_image` | **M** | Mirror `generate_qr` exactly (`tools.py:423-503`): build `AssetGenerationRequest`, call `self.core.generate_asset(provider, request, asset_id)` (already exists, `core.py:199`), upsert via `{kind: upsert_asset}`, return asset_id + provenance/license. Register in `factory.py` tool list (currently has `generate_qr`, no `generate_image`). |
| `place_asset_in_node` / `place_asset_in_slot` tools | **M** | Named in the `generate_qr` docstring but **do not exist**. Add as thin wrappers over the reversible Place ops, carrying `fit`/`focal_point`/`alt`. |
| Decide → prompt → generate → place → critique flow | **M** | Coordinator step that (1) decides image-worthiness, (2) authors a brand-conditioned prompt, (3) picks aspect from target node/slot geometry, (4) places `fit:cover` + focal, (5) emits scrim when text overlaps. See §3. |
| Parallel generation | **M (defer)** | Brilliant fires all `generate_image` calls in one turn (`integration.md:40-42`: 10 parallel ≈ 1 wall-clock). Lumen loop is one tool call at a time. Needs async/batched provider + a batch-accepting tool. Defer past v0. |
| Image-aware repair routing | **M** | `RepairClass.asset_tool` exists but no `loop.py` mapping. Add classification: `imagery` critique → regenerate-with-revised-prompt / recrop / add-scrim / replace / remove — not a geometry patch. |

### (e) Knowledge / catalog

| Work | Effort | Detail |
|---|---|---|
| `knowledge/images/` decision + prompt + templates doc | **S** | Port Brilliant: WHEN to generate vs not (`prompts.md:3-11`), image-vs-svg-vs-vectorize rule (`svg/integration.md:5-16`), 5-component prompt craft (Subject+Medium+Composition+Lighting+Quality, no in-image text, `prompts.md:13-43`), per-use-case templates (hero/product/portrait/food/texture, `templates.md:9-43`). Today no `images/` dir exists; `asset-placement.md:26` says generation is "Recognized But Not Lowered" — update it. |
| Placement idioms incl. text-over-image scrim | **S** | Document the `Frame{clip,radius} > Image{cover,focal}` + sibling scrim-rect idiom (our equivalent of Brilliant's `f[(img(...)),(f2,solid($neutral.intense,o($visibility.mid)))]`, `integration.md:32-38`). |
| Asset catalog/search surfaced to agent | **M** | Agent gets a Brand Kit but **no list of available image assets**; grammar requires a pre-existing `asset(id)`. Add an `asset_search`/`list_assets` tool over the store + brand library and inject available roles/ids per iteration, so the agent can reuse approved imagery instead of always regenerating. |
| Image-bearing catalog blocks | **S–M** | Add hero/feature/gallery blocks that include an image region + scrim + text slot, so the agent composes from vetted layouts rather than free-handing image placement. |

### (f) Visual critic

| Work | Effort | Detail |
|---|---|---|
| Imagery rubric in the **live** (Python) critic | **S–M** | `VISUAL_REVIEWER_SYSTEM_PROMPT` (`prompts.py:172-220`) checks alignment/spacing/etc. and even leans **anti-image** (clause H "Prefer information on surfaces"). It has **no** imagery check. Add an `imagery` category to `CritiqueCategory` (today: `asset_use` only, no `imagery`) and rubric covering: should an image be here at all; relevance to message; aspect/crop fit; **text legibility over image / scrim adequacy**; resolution/blur vs rendered size (DPI); garbled in-image text; on-brand style; placeholder-vs-real credibility. |
| Repair recipe | **S–M** | Map imagery critique → regenerate / add-scrim / reframe (ratio) / replace. Wire to the repair routing in (d). |

> Note: the live critic is the **Python** one (`schemas.py`/`prompts.py`). The Rust `VisualIssueCategory::Imagery` is scaffolding that does **not** gate the running loop — imagery judging must be added Python-side. (See Deviation B.)

## 3. The agent perspective (the emphasis)

Today the agent **never** decides to use, prompts for, generates, or places a content image, and the critic never judges imagery. The full chain is absent. The smallest set of changes to make it use images **well, not gratuitously**, mirroring Brilliant's decision rules:

1. **A DECIDE step (the most important, cheapest change).** Before generating, the coordinator answers: *does this surface need imagery, and what role?* Port Brilliant's decision table (`prompts.md:3-11`, `svg/integration.md:5-16`) verbatim into a knowledge doc + coordinator prompt:
   - **photo / product / portrait / food / texture → `generate_image`**
   - **icon / logo → SVG** (`svg(icon:)`, or brand `logo.*` token)
   - **abstract geometric → shapes; simple geometric → gradients/solids**
   This is the guardrail against gratuitous images. Without it, wiring a model just produces *more* bad designs. Note the current reviewer prompt's anti-image clause H must be softened — it currently biases the agent away from imagery entirely.

2. **A PROMPT-AUTHORING skill.** Force the 5-component structure (Subject + Medium + Composition + Lighting + Quality), specificity over keywords, and **no in-image text** (`prompts.md:13-43`). Feed brand tone/palette into `brand_notes` (the field already exists). Per-use-case templates from `templates.md`.

3. **A GENERATE tool** (`generate_image`) + **PLACE tools** — §2(d). Pick aspect ratio from the **target node/slot geometry** so a 1:1 isn't stretched into 16:9 (`integration.md:48-50`); place `fit:cover` with a sensible focal point.

4. **The SCRIM convention.** Whenever text overlaps an image, the agent emits a scrim rect (`opacity.scrim`) below the text — Brilliant's hero pattern (`integration.md:32-38`). Composable today; make it a hard agent recipe, not optional.

5. **A CRITIC dimension + REPAIR loop** — §2(f)/(d). The critic gates on relevance, crop, legibility-over-image, resolution, and "is an image even warranted." Failures route to regenerate-with-revised-prompt / add-scrim / reframe — closing the loop.

**Minimal agent slice:** decide-doc + softened reviewer clause H → `generate_image` + `place_asset_in_node` tools → scrim recipe → `imagery` critic category. That alone gets tasteful imagery; parallel gen, catalog search, and reference-image style-locking layer on after.

## 4. Brilliant-faithful design + DEVIATIONS

**We mirror:** the decision table (image vs svg vs shapes vs gradient); 5-component prompt craft + per-use-case templates; aspect-match-to-frame + imageSize-by-role; text-over-image **scrim below text**; parallel generation; reference-image style consistency; an imagery critic axis. All have direct Brilliant evidence (`images/prompts.md`, `templates.md`, `integration.md`, `svg/integration.md`).

**Forced deviations — flag explicitly:**

- **Deviation A — image-as-fill.** Brilliant's canonical idiom is image-as-**FILL** on a frame: `f[(img(hero.png))]`, with scrim as a stacked fill `f[(img(...)),(f2,solid(...,o(mid)))]`. Lumen's `Paint` enum has **no Image variant** (confirmed `scene.rs:653-658`). We express the same visual result as `Frame{clip:true, corner radius} > Image{fit:cover, focal_point}` with a **sibling** semi-transparent Rect/gradient scrim above it. *Why:* this renders pixel-correctly today across SVG and Skia with zero core change; a true `Paint::Image` is an L change across Paint/DSL/scene/validation/both renderers/PDF/fixtures. The interim is slightly more fragile on z-order/clip/rounding but is the right v0 trade. Build `Paint::Image` later only if the fill ergonomics matter.
- **Deviation B — critic location.** Brilliant judges imagery in its critic; Lumen has a Rust `VisualIssueCategory::Imagery` enum that does **not** run. The **live** critic is Python (`schemas.py`/`prompts.py`). *Why:* the loop uses the Python critic; imagery judgment must be added there, not in the Rust scaffolding. We reuse/extend the Python `CritiqueCategory`.
- **Deviation C — where the network call lives.** Brilliant's runtime calls the model directly. Lumen's `lumen-assets` is sync/offline (no http deps) and the helper is a one-shot subprocess. *Why:* we put the HTTP call in the Python API layer (already async) and feed bytes through `ingest_asset`, rather than adding `reqwest`/`tokio` to the sync Rust crate.
- **Deviation D — image post-process filters** (duotone/halftone/grain as fills, `reference/image-filters.md`) have **no Lumen analog** and would need new fill/effect types + shader support in both renderers (L). **Defer entirely** — not needed for v0 imagery.

## 5. Recommended sequencing

Get a **thin end-to-end slice** first — one generated hero image, placed as a cover-fit `Frame>Image`, with a scrim under text, judged by the critic — then layer up. Each step is independently shippable.

**Slice 0 — thin end-to-end (proves the loop):**
1. **Real T2I provider** behind `generate_asset`, network call in Python API layer (§2a). M. *Unblocks everything; replaces the solid-color stub.*
2. **`generate_image` + `place_asset_in_node` tools**, mirroring `generate_qr`; register in `factory.py` (§2d). M.
3. **Decide-doc + prompt-craft knowledge** (port Brilliant decision table + 5-component prompts + hero template); soften reviewer clause H (§2e, §3.1–2). S.
4. **Scrim recipe** — agent emits scrim rect under text over images, using `opacity.scrim` (§2b, §3.4). S.
5. **`imagery` critic category + basic rubric** (relevance, legibility-over-image, crop fit) + regenerate/add-scrim repair routing (§2f, §2d). S–M.

> After Slice 0, a design can contain a real, brand-conditioned, scrimmed hero image that the agent chose deliberately and the critic gates.

**Slice 1 — fidelity & ergonomics:**
6. `aspect_ratio`/`image_size`/`reference_asset_ids` on `AssetGenerationConstraints` + aspect-match-to-frame (§2b). S–M.
7. Generation cache keyed on prompt+constraints+model (§2a). M.
8. Asset catalog/search tool + image-bearing catalog blocks (§2e). M.
9. Parallel generation for multi-image designs (§2d). M.

**Slice 2 — quality follow-ups (defer):**
10. Intrinsic-aspect layout sizing (§2b). M.
11. PDF image embedding + EffectFeature matrix entry (§2b). M + S.
12. `Paint::Image` variant if fill ergonomics prove necessary (Deviation A). L.
13. Image post-process filters (Deviation D). L.

**Load-bearing rationale:** the engine and pipeline are ready (QR proves the full loop), so the highest-leverage, lowest-risk first moves are (1) one real provider and (2) the `generate_image` tool — those two alone put real photos in designs. The *agent brain* (decide-doc + prompt craft + scrim recipe + imagery critic) is what makes them *good*, and it is mostly cheap S/M knowledge + prompt + one critic category — no schema churn. Defer the two L items (`Paint::Image`, filters) entirely for v0.

Key files: `crates/lumen-assets/src/providers.rs`, `crates/lumen-assets/Cargo.toml`, `crates/lumen-api-helper/src/main.rs`, `crates/lumen-core/src/assets.rs`, `crates/lumen-core/src/scene.rs`, `apps/api/lumen_api/{main.py,core.py}`, `apps/agent_runtime/lumen_deepagent/{tools.py,factory.py,prompts.py,schemas.py,loop.py}`, `apps/agent_runtime/knowledge_docs/knowledge/{images/* (new),assets/asset-placement.md,lumen-dsl/grammar.md}`.
