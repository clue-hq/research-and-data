# Image Model & Imagery — Slice 0 + Slice 1 Spec (Brilliant-faithful)

Authored 2026-06-19 from a fan-out over our stack (`crates/lumen-*`, `apps/{api,editor,agent_runtime}`) + Brilliant's image/editor/effects knowledge. Companion to `IMAGE-MODEL-SCOPE.md`.

> **Product bar (non-negotiable):** Slice 0 is a **production-grade *usable*** feature for enterprise day-to-day use — **not** a throwaway MVP. Output quality must be good enough that a team uses it for real social/deck/one-pager work. Slice 1 raises it toward **professional grade**. Slice 2+ is deferred. Every Slice-0 item below is justified by "an enterprise user would hit this on day one."

---

## 0. Principles (ported from Brilliant)

1. **Generate only what you can't build.** The decision rule is the guardrail against gratuitous AI imagery. Route by content type:
   | Content | Mechanism | Slice |
   |---|---|---|
   | Photo, product, portrait, food, texture, **raster illustration** | `generate_image` (raster T2I; illustrations = illustration-style prompt) | **0** |
   | **Icon / simple flat illustration / logo glyph** | **icon library** → `svg(icon:name)` lowered to `VectorNode` (curated, recolorable, reliable) | **0** |
   | Editable **generative** vector illustration | `generate_svg` (generative vector model) | **1** |
   | Existing raster → editable paths | `vectorize_image` | **1** |
   | Abstract / decorative | shapes + gradients | exists |
   | Animated / shader decor | WebGL shaders | defer |
2. **Image is placed onto a target, ratio derived from the target, default Fill/cover, then refined** — never a free-floating image object the user pre-sizes. (Brilliant `ai.md`, `crop.md`.)
3. **Text over image always gets a scrim** beneath the text (legibility). (Brilliant `images/integration.md`.)
4. **The agent decides; the human refines.** Both the agent loop and the editor issue the *same* canonical ops (`upsert_asset` + `place_asset_in_node`) against the *same* node id, preserving identity + slot bindings.
5. **Illustrations are first-class, bifurcated** (raster vs vector) — your explicit ask. Enterprise decks lean on icons/spot illustrations more than photos, so Slice 0 ships *both* a raster path and a reliable vector-icon path.

**Why this is mostly wiring, not a rebuild:** `NodeKind::Image{asset_id,alt}` + `AssetPlacement{fit,focal_point,preserve_transparency,alt_text}` + `ImageFitMode{Contain,Cover,Crop}` + reversible `PlaceAssetInNode/PlaceAssetInSlot/UpsertAsset/RemoveAsset` ops + **real Skia & SVG export of cover/contain/focal-crop** + asset store/ingest/probe/license + slot image-policy validation **all exist today**. The QR generator already exercises the full generate→ingest→store→place→render→export loop. The gaps are the **generation providers**, **editor pixel-rendering + controls**, the **agent brain**, and the **imagery critic** — not the rendering substrate.

---

## 1. EDITOR aspect (human-in-canvas)

**Exists today:** `AssetBrowserPanel` (upload, search-by-kind, "Place" into selected node via `buildNodePlacementOperations` = upsert+place); `assetLibrary.ts` (fetch/upload/thumbnail/bytes URLs, placement builders); image nodes are selectable/movable/resizable/clippable/corner-radius via the generic node path; `SlotInspector` shows `image_policy` (read-only) and validates image slots; `AgentChatPanel` (generic prompt→`/agent/turn-preview`). Backend routes all exist (`POST /assets`, `POST /assets/generate`, `GET /assets/{id}/bytes`, `/thumbnail`).

### Slice 0 — production-usable editor
| # | Item | Effort | Detail |
|---|---|---|---|
| E0.1 | **Render real pixels on canvas** | **M** | *The single biggest blocker.* Today `ImageNode` draws a gray placeholder + alt text in **both** CanvasKit and Konva (`renderDiagnostics.ts: EDITOR_RENDER_IMAGE_PLACEHOLDER`). Carry a byte/thumbnail URL on the image descriptor (`renderAdapter.ts` image branch → `GET /assets/{id}/bytes`); draw via CanvasKit `MakeImageFromEncoded` (`drawDescriptors.ts`) + Konva `Image`, honoring **fit + focal_point + clip + corner-radius** — reuse the exporters' `focal_crop_geometry` so editor == export. Without this, generated/placed images are invisible until export — reads as a bug, not a feature. |
| E0.2 | **Image inspector: Fit + Focal + Alt** | **M** | `InspectorPanel` has no image section (an image node falls through to a color swatch). Add: Fit dropdown (`cover`/`contain`/`crop`), a **draggable focal-point dot** on a canvas overlay (cheap; reuses `focal_crop_geometry`), and an editable **alt-text** field. Each edit emits the existing `asset_placement` `NodePatch` / `place_asset_in_node`. |
| E0.3 | **Generate-into-this-node/slot** | **M** | Select an image node (or empty image slot) → prompt box → "Generate". Calls `POST /assets/generate` with `target_node_id` + prompt + constraints (size/ratio derived from the node bounds), then runs `upsert_asset` + `place_asset_in_node` against the **same node id**. This is the human entry point for the feature. |
| E0.4 | **Regenerate / Replace** (in place) | **S** | Inspector actions on a selected image: **Regenerate** (re-run generation on the same node, prompt prefilled/editable); **Replace** (open library scoped to the node) — both **carry the existing `AssetPlacement` forward** (don't reset to `{}`), preserving fit/focal/slot binding. Daily enterprise action (swap stock for approved). |
| E0.5 | **Generation status on the target** | **S** | Generation is multi-second and can fail. Surface `AssetStatus` Pending→Ready→Failed as a spinner/skeleton on the target node, then the image or an error carrying the `LUMA*` diagnostics that already flow back. Prevents dead-air UX. |
| E0.6 | **Insert an icon/illustration from the library** | **S** | Surface the bundled icon set (see §5 G0.4) in `AssetBrowserPanel` as a searchable category; "Place" lowers `svg(icon:name)` to a `VectorNode`. Covers the bulk of business-deck "illustration" needs reliably. |

### Slice 1 — toward professional
- **Interactive crop editor** (L): double-click an image to enter crop; 30%-opacity ghost of the uncropped area; pan/resize(8 zones, Shift/Ctrl aspect-lock)/rotate the image within the container; container resize/rotate auto-compensates so the image stays fixed in world space; each step its own undo. (Brilliant `crop.md`.) Slice 0's fit-dropdown + focal-dot is the cheap stand-in.
- **Reference-image editing in the editor** (M): @mention/attach an element or paste an image as a style/edit reference; "change one thing" iteration. (Brilliant `ai.md`.)
- **Resolution tier picker** (S): expose 1K/2K/4K (Slice 0 hardcodes a sensible size by role).
- **Richer AI chat ergonomics** (M): attachments, @mention-element-as-context, queued follow-ups, edit-and-resend, stop/cancel.
- **License/provenance chip** in the inspector (S): show rights for generated/placed imagery (core already validates LUMA0400/0401).

---

## 2. CANVAS & RENDERS aspect

**Exists today (high quality):** Skia rasterizer + SVG exporter both honor `Contain/Cover/Crop` + `focal_crop_geometry` + corner-radius clip; SVG even embeds raster as base64 data-URI with `preserveAspectRatio` + focal clip-path; Skia renders SVG-bytes assets natively. `Paint` = `Solid/LinearGradient/RadialGradient/Token`; ordered per-node fill stack; `EffectKind::DropShadow` rendered in Skia + SVG. Asset bytes resolved at export via `StoreBackedResolver`.

### Slice 0
| # | Item | Effort | Detail |
|---|---|---|---|
| C0.1 | **Editor↔export render parity** | (part of E0.1) | Editor canvas must draw images with the *same* fit/focal math as export. Lock with a golden test: same scene → editor raster ≈ Skia export. |
| C0.2 | **Scrim/overlay rendering** | **none (compose)** | Scrim = a sibling semi-transparent `Rect` (solid or linear-gradient) above the `Image` node, using `opacity.scrim` (0.56) / `opacity.overlay` (0.88). Renders correctly today; the work is the *recipe* (§4/§5), not the engine. |
| C0.3 | **Raster export (PNG/retina)** | **exists; verify** | Confirm 2× retina raster of image-bearing scenes is clean; add image-bearing golden fixtures. |

### Slice 1
- **PDF image + gradient fidelity** (M): PDF currently drops images (`pdf.rs:286 warn_unsupported`) and gradients (`pdf.rs:404 Unsupported`). Rasterize-to-PDF with soft masks (Brilliant's approach) so enterprise print decks with imagery export faithfully. + add an `ImageFill`/`RasterImage` entry to the `EffectFeature` matrix so the PDF drop surfaces through the central LUMX channel (S).
- **Intrinsic-aspect layout sizing** (M): images measure as a fixed box (`layout.rs:655`); add optional auto-height from the asset's true ratio so authors needn't set both dims.
- **Angular/conic gradient** Paint variant (S): Brilliant has Solid/Linear/Radial/Angular; we lack Angular (overlay/treatment polish).

---

## 3. GRAMMAR / DSL aspect

**Exists today:** `image asset(id)` / `img(id)` lowers to `NodeKind::Image`; `vector path("…")` / `v(…)` lowers to `VectorNode`; `f[(id,paint)]` fill stack; `shadow(...)` effect; `s()/clip/rd()` geometry. The `svg(icon:name)` kind is **parsed but not lowered** (`LUMD0703`).

### Slice 0
| # | Item | Effort | Detail |
|---|---|---|---|
| G0.1 | **Expose fit/focal/alt/slot on image authoring** | **S** | Ensure the DSL/placement path lets the author set `fit`, `focal_point`, `alt`, and `slot()` so generated placements are complete + validated (the ops already carry placement). |
| G0.2 | **Aspect hint on generation** | **S** | Add `aspect_ratio` + `image_size` (1K/2K/4K) + `reference_asset_ids` to `AssetGenerationConstraints` (serde-default → back-compat); provider translates ratio→w/h. Mirrors Brilliant `aspectRatio`/`imageSize`/`referenceElementIds`. |
| G0.3 | **Lower `svg(icon:name)` → `VectorNode`(s)** | **M** | Resolve the icon name against the bundled set, lower each top-level SVG shape to a `VectorNode` (grouped), token-recolorable via `$color.*`. Clears `LUMD0703`. Gives the agent + catalog a reliable icon/illustration primitive. |
| G0.4 | **Scrim idiom documented in grammar/text** | **S** | Bless the `Frame{clip,rd} > Image{cover,focal}` + sibling scrim-rect pattern in `knowledge/lumen-dsl`. |

### Slice 1
- **`Paint::Image` fill variant** (L): image as a z-ordered fill on any shape/frame (Brilliant's canonical model) so crop/strokes/radius compose for free. Touches Paint enum + DSL + scene + validation + both renderers + PDF + fixtures. Slice 0's `Frame>Image` + sibling scrim achieves the same look. **(Deviation A.)**
- **`img()` inside the fill list** (tied to above).

---

## 4. AGENTS aspect (the emphasis)

**Exists today:** intent classifier routes `asset_generation_or_placement` to an `AssetTool`; `AgentAssetRequest::{GenerateImage,GenerateSvg,VectorizeImage,PlaceAsset}` enum; `CritiqueCategory.asset_use`; `RepairClass.asset_tool`; `recommend_edit_surface` detects "generate image"/"vectorize" intent; `tools.generate_qr` is the exact reference template (calls core → ingest → `upsert_asset` → returns id). **None of it fires** — there is no `generate_image` tool, no decision rule, no imagery critic; the reviewer prompt's clause H even biases *away* from imagery.

### Slice 0 — the decide → prompt → generate → place → critique loop
| # | Item | Effort | Detail |
|---|---|---|---|
| A0.1 | **DECIDE step** (most important, cheapest) | **S** | Coordinator/knowledge rule: *does this surface need imagery, and what role?* Port Brilliant's decision table (photo→`generate_image`; icon/flat-illustration→icon library; abstract→shapes). The guardrail against gratuitous images. **Soften reviewer clause H** so the agent isn't biased against imagery entirely. |
| A0.2 | **`generate_image` tool** | **M** | Mirror `generate_qr` (`tools.py:423-503`): build `AssetGenerationRequest{prompt,output_kind,target_node_id,constraints{w,h,brand_notes,aspect_ratio}}`, call `core.generate_asset(provider,request,asset_id)`, `upsert_asset`, return id+provenance. Register in `factory.py`. |
| A0.3 | **`place_asset_in_node` / `place_asset_in_slot` tools** | **M** | Thin wrappers over the reversible Place ops, carrying `fit:cover` + a sensible `focal_point` + `alt`. Aspect derived from target geometry (no 1:1-stretched-to-16:9). |
| A0.4 | **`place_icon` (library)** | **S** | Tool to drop a library icon (`svg(icon:name)`→VectorNode) for iconographic needs — the agent's vector-illustration path in Slice 0. |
| A0.5 | **PROMPT-craft skill** | **S** | Force Brilliant's 5-component structure (Subject + Medium/Style + Composition + Lighting + Quality), specificity over keywords, **no in-image text**, brand tone via the existing `brand_notes`. Per-use-case templates (hero/product/portrait/food/texture/illustration). |
| A0.6 | **SCRIM recipe** | **S** | Hard rule: text over image ⇒ emit a scrim rect (`opacity.scrim`) beneath the text. |
| A0.7 | **Imagery repair routing** | **S–M** | Wire `RepairClass.asset_tool`: an `imagery` critique routes to regenerate-with-revised-prompt / recrop(focal) / add-scrim / replace / remove — **not** a geometry patch. |
| A0.8 | **Generation cache** | **M** | Cache `(normalized_prompt, constraints, model, reference_ids)`→asset_id *before* calling the provider. The quality loop re-requests the same hero across iterations; the byte-digest store dedup happens only *after* the (paid, non-deterministic) call. **Slice-0 because** without it every iteration re-pays and the design churns its imagery — not usable. |

### Slice 1
- **Parallel generation** (M): fire all `generate_image` calls in one turn (Brilliant: 10 parallel ≈ 1 wall-clock). Needs async/batched provider + batch-accepting tool. (Slice 0 = one at a time; fine for the common 1-hero case.)
- **`generate_svg` tool** (generative vector) + **`vectorize_image` tool** (M each).
- **Reference-image style-lock** across generations (M).

---

## 5. TOOLS & EFFECTS aspect (incl. illustrations)

**Exists today:** `Paint{Solid,Linear,Radial,Token}`; ordered fill stack; `EffectKind::DropShadow` (Skia + SVG); `VectorNode{path_data}` renders; full strokes; `opacity.scrim`/`opacity.overlay` tokens; `EffectValue::{Shadow,Blur,BackdropBlur}` modeled but only DropShadow rendered. **Real generation = QR only; T2I + vectorize are stubs.**

### Slice 0
| # | Item | Effort | Detail |
|---|---|---|---|
| **G0** | **Real raster T2I provider** | **M** | New `AssetGenerationProvider` impl (`image-gen-v1`) behind the existing trait/registry, replacing `StubImageProvider`. **Network call lives in the Python API layer** (already async) feeding bytes through `ingest_asset` — avoids adding `reqwest`/`tokio` to the sync `lumen-assets` crate (**Deviation C**). Map prompt+constraints→API; decode→`ProviderArtifact` with license/provenance. Env-keyed config (key/base-url/model/version pin). Bounded sync timeout + retry. |
| **I0** | **Bundled icon/illustration library** | **M** | Curate a tokenizable icon/flat-illustration set; lower `svg(icon:name)`→`VectorNode`(s), recolorable via `$color.*`. This is the **reliable** illustration path (a curated set beats a hit-or-miss generative-vector model for "usable production"). Brilliant itself uses `svg(icon:name)` library refs for icons. |
| **S0** | **Scrim + gradient overlay** | **S** | Knowledge recipe + (optional) a tiny helper to stack a solid or linear-gradient scrim over an image. All primitives exist. The #1 enterprise use (text over hero photo). |

### Slice 1
- **`generate_svg`** generative editable-vector illustrations → native `VectorNode`s, grouped, token-recoloring (L) + **`vectorize_image`** raster→paths (M).
- **`colorAdjust`** (exposure/contrast/saturation, the high-value subset) then **duotone / halftone / grain / posterize** image-filter family (L) — "makes photos feel designed."
- **Inner shadow / inner glow / background-blur (frosted glass)** effects (M): new `EffectKind`/`PaintStyle` + Skia `saveLayer`/`BackdropFilter` + SVG filter/raster fallback.

### Defer (Slice 2+)
- Animated/interactive **WebGL shaders** (metaballs, liquid metal, iridescent…) + WebGL HTML export — decorative, irrelevant to static enterprise output; highest cost / lowest relevance.
- Interactive **pen/pencil vector authoring**, node editing, boolean ops, vector snapping — a separate vector-editing workstream, orthogonal to *generating* illustrations.

---

## 6. Slice 0 acceptance criteria ("production-grade usable")

A Slice 0 ship is accepted when, for real enterprise prompts (social ad, one-pager, deck slide):
1. The agent **decides correctly** when to use a photo vs an icon vs nothing (no gratuitous imagery; the decision table is honored).
2. A generated **photo renders as real pixels in the editor** (not a placeholder), cover-fit + focal, inside a clipped/rounded frame, **identical to export**.
3. **Text over an image is legible** — a scrim is present and the critic gates legibility-over-image.
4. The agent picks an **aspect that matches the frame** (no stretched images), and **re-uses the cached image** across loop iterations (no churn / re-pay).
5. A human can **generate-into a node, recrop via focal, regenerate, replace, edit alt**, and sees **pending/ready/failed status** — all without delete-and-re-place.
6. **Icons/flat illustrations** are available and reliable via the library.
7. The **imagery critic axis** gates relevance, crop/aspect fit, legibility, and resolution-vs-rendered-size (DPI); failures route to regenerate/recrop/add-scrim/replace.
8. Output **quality is good enough to use** for day-to-day business artifacts (the bar: a designer would ship it with minor tweaks, not redo it).

---

## 7. Sequenced build plan

**Slice 0 — production-usable (order = dependency order):**
1. **G0** real raster provider behind `generate_asset` (Python network call). *Unblocks everything; kills the solid-color stub.* — M
2. **E0.1** editor canvas pixel rendering (CanvasKit/Konva, reuse export fit math). *Without this the feature looks broken.* — M
3. **A0.2 + A0.3** `generate_image` + `place_asset_in_node` tools (mirror QR), register in `factory.py`; aspect-from-frame. — M
4. **A0.1 + A0.5 + A0.6** DECIDE doc + prompt-craft + scrim recipe; soften reviewer clause H. — S
5. **E0.2 + E0.3 + E0.4 + E0.5** image inspector (fit/focal/alt) + generate-into-node + regenerate/replace + status. — M
6. **A0.8** generation cache (prompt+constraints+model). — M
7. **G0.2** aspect/size/reference fields on constraints. — S
8. **I0 + G0.3 + A0.4 + E0.6** icon library + `svg(icon:name)` lowering + `place_icon` + library UI. — M
9. **A0.7 + critic** `imagery` `CritiqueCategory` + rubric + repair routing. — S–M
10. **S0 / G0.4** scrim helper + grammar docs; image-bearing catalog block(s) + golden fixtures + tests. — S

> After Slice 0: the agent deliberately chooses imagery, generates a brand-conditioned, aspect-matched, scrimmed photo (or places a library icon), the human can refine it in the editor, and the critic gates quality — usable for real work.

**Slice 1 — toward professional:** interactive crop editor; `generate_svg` + `vectorize_image`; reference-image style-lock; resolution tiers; `colorAdjust` + duotone/halftone/grain; inner-shadow/glow/glass; angular gradient; `Paint::Image` fill; PDF image+gradient fidelity; richer AI chat ergonomics; license/provenance chip; intrinsic-aspect sizing.

**Defer (Slice 2+):** animated WebGL shaders; interactive pen/node vector editing.

---

## 8. Deviations from Brilliant (flagged)

- **A — image-as-fill:** Brilliant attaches images as a *fill* (`f[(img(...)),(scrim)]`); we use `Frame{clip,rd} > Image{cover,focal}` + a *sibling* scrim. Same pixels, zero core change; `Paint::Image` is a Slice-1 ergonomics upgrade.
- **B — critic location:** imagery judging lives in our **Python** critic (the Rust `VisualIssueCategory::Imagery` enum doesn't gate the running loop).
- **C — network call site:** in the Python API layer (async), not the sync Rust helper crate.
- **D — illustration default:** Brilliant defaults iconographic work to a *generative* vector model (`generate_svg`) in v1; we ship a **curated icon library** in Slice 0 (more reliable for "usable production") and defer generative-vector to Slice 1. *Deliberate quality-over-parity choice — flag for sign-off.*
- **E — image post-process filters & shaders:** deferred to Slice 1 / Slice 2+; not needed for a usable first feature.
