# Subsystem map: Render/export contract + assets (crop, opacity, color, image)

Scope: how OPACITY, CROP, fills/COLOR, strokes, and IMAGES are represented and
rendered; whether the visual properties the user wants to edit are already
modeled or missing; what data a node must carry to render; whether
freehand/absolute positioning has a render path; and the assets pipeline as it
bears on crop.

All "EXISTS TODAY" claims are cited to file:line. Anything labelled
**SPECULATION** or **MISSING** is not in the code.

---

## 1. The node model (what a node carries)

`crates/lumen-core/src/scene.rs:268-320` defines `Node`. The fields that matter
for this study:

- `transform: Transform` — `scene.rs:273`, struct at `scene.rs:503-526`
  (`x, y, rotation, skew_x, skew_y, flip_x, flip_y`). This is the AUTHORED
  position. Note: there is no separate "absolute vs relative" flag on the node.
- `size: SizeSpec` — `scene.rs:274`; `SizeSpec` at `scene.rs:528-541` holds two
  `Dimension`s. `Dimension` (`scene.rs:543-550`) = `Fixed(f64) | Hug | Fill{weight} | Token{token}`.
- `fills: Vec<Fill>` — `scene.rs:276`. A stack (bottom-to-top).
- `strokes: Vec<Stroke>` — `scene.rs:277`.
- `effects: Vec<Effect>` — `scene.rs:282` (drop shadows; serde-skipped when empty).
- `corner: CornerRadii` — `scene.rs:283`.
- `opacity: f64` + `opacity_token: Option<String>` — `scene.rs:284-286`. Default 1.0 (`scene.rs:310`).
- `source_asset_id: Option<AssetId>` — `scene.rs:288`.
- `asset_placement: Option<AssetPlacement>` — `scene.rs:290`. **This is where image fit/crop intent lives.**
- `clip: bool` — `scene.rs:291`.
- `layout: Option<AutoLayoutProps>` — `scene.rs:292`.
- `computed: Option<ComputedGeometry>` — `scene.rs:293`. **The solved geometry, written by the layout engine.**
- `locked: bool` — `scene.rs:295`.

`ComputedGeometry` (`scene.rs:704-708`) = `{ layout_bounds: Rect, render_bounds: Rect }`.
`Rect` is `{x, y, width, height}` (`scene.rs:696-702`). `layout_bounds` is the
solved box in PAGE-ABSOLUTE coordinates; `render_bounds` is its
rotation/skew/flip-expanded AABB (computed by `render_bounds_for`,
`layout.rs:1514-1558`).

---

## 2. OPACITY — exists, fully renderable, already editable

- **Model**: `node.opacity: f64` (`scene.rs:284`) with optional token override
  `opacity_token` (`scene.rs:286`). Group/node-level only. There is no
  per-fill alpha channel separate from the color's own alpha.
- **DSL authoring**: `o(...)` / `opacity(...)` property, parsed at
  `dsl.rs:3337` and lowered at `dsl.rs:2540-2547` (number sets `opacity`, `$token`
  sets `opacity_token`) and `dsl.rs:3892-3899`.
- **Edit op**: `NodeEditPatch.opacity: FieldPatch<f64>` and
  `opacity_token: OptionalFieldPatch<String>` (`editing.rs:586-587`), threaded
  to the node patch at `editing.rs:979-980`.
- **Render — SVG**: `svg.rs:255-259` emits `opacity="…"` when `< 1.0`.
- **Render — PNG/Skia**: `render.rs:202-210` — opacity `< 1.0` (or any shadow)
  forces a `save_layer` with `set_alpha_f(opacity)`. So opacity composites a
  whole subtree, matching SVG group opacity.
- **Render — editor preview (Konva/CanvasKit)**: `renderAdapter.ts:179`
  copies `opacity` into the descriptor; CanvasKit applies it via a layer paint
  (`drawDescriptors.ts:70`).
- **Export support matrix**: opacity is not a tracked `EffectFeature`
  (`render_contract.rs:73-84`), i.e. it is assumed natively supported by all
  raster/vector targets.
- **PDF**: opacity is NOT applied — the PDF writer never emits an alpha/`gs`
  ExtGState (no opacity handling in `pdf.rs`). **MISSING for PDF only.**

Verdict: **EXPOSE EXISTING.** Opacity is modeled, edited, and rendered
everywhere except PDF.

---

## 3. COLOR / fills / strokes — exists, fully renderable, already editable

### Color model
`Color` enum (`scene.rs:666-672`): `Hex{value} | Token{token} | Oklch{l,c,h,alpha}`.
`Paint` enum (`scene.rs:651-658`): `Solid{color} | LinearGradient{angle,stops} | RadialGradient{stops} | Token{token}`.
`ColorStop` = `{color, position}` (`scene.rs:660-664`).

`Fill` = `{id: PaintId, paint: Paint}` (`scene.rs:552-556`). `Stroke`
(`scene.rs:558-574`) = `{id, paint, width, width_token, dash, cap, join, align}`.

### DSL authoring
`parse_color` (`dsl.rs:4596-…`): `$token`, `oklch(l,c,h[,alpha])`, hex, etc.
`parse_paint` handles `solid(...)`, `linear(...)`, `radial(...)`
(`dsl.rs:4515-4544`). **Caveat (MISSING):** `solid(color, opacity)` form is
rejected — "opacity arguments are parsed but not lowered" (`dsl.rs:4527-4536`).
Per-fill opacity must instead go through the color's own alpha (e.g.
`#RRGGBBAA`) or node `o(...)`.

### Edit ops
- Whole-stack replace: `fills: FieldPatch<Vec<Fill>>`, `strokes: FieldPatch<Vec<Stroke>>` (`editing.rs:575-576`).
- Per-entry edits: `fill_edits: Vec<StackEntryEdit<Fill,PaintId>>`,
  `stroke_edits` (`editing.rs:580-582`). `StackEntryEdit` (`editing.rs:550-567`)
  supports `Set{id,value} | Add{entry,index} | Remove{id} | Reorder{id,index}`.
  So recolor = a per-fill `Set` patch carrying a new `Paint`. **Fully exists.**

### Render
- **SVG**: `paint_attrs` / `paint_layer_attrs` (called at `svg.rs:295-302` etc.);
  gradient defs and `<linearGradient>`/`<radialGradient>` math near `svg.rs:806-868`
  parity.
- **PNG/Skia**: `fill_paint` (`render.rs:713-725`), `stroke_paint`
  (`render.rs:732-788`), `apply_paint_source` (`render.rs:792-823`), gradient
  shaders (`render.rs:828-868`), hex parse (`render.rs:983-1012`), OKLCH→sRGB
  (`render.rs:1015-1038`). Multi-fill / multi-stroke stacks are painted in order.
- **Editor preview**: `paintToCss`/`colorToCss` (`renderAdapter.ts:296-318`),
  full stacks via `fills`/`strokes` descriptors (`renderAdapter.ts:183-186`),
  Konva paint props (`renderAdapter.ts:387-435`).
- **Token resolution**: a `Paint::Token` / `Color::Token` that is unresolved at
  export time renders as nothing and emits diagnostic `LUME0206`
  (`render.rs:911-923`, SVG `unresolved_brand_token_diagnostics`
  `svg.rs:1092-…`). The brand/token resolver lives elsewhere (brand.rs); the
  renderer just consumes resolved colors.
- **PDF**: solids only — `pdf_rgb` (`pdf.rs:925-…`); gradients are
  `PaintResult::Unsupported` (`pdf.rs:404, 414`).

### Export support matrix (per-format degradation)
`render_contract.rs:121-156`: SVG/PNG = `Native` for everything except
`StrokeAlignment` = `Approximate`. KonvaScene approximates stroke-alignment,
shadow-spread, layered-shadows. PDF: multi-fill/stroke/dash/cap-join/stroke-align
= `Approximate`; gradients + all shadows = `Unsupported`. Non-native features
emit `LUMX0001`/`LUMX0002` diagnostics (`render_contract.rs:226-291`) so
degradation is loud, never silent.

Verdict: **EXPOSE EXISTING.** Recolor, gradient, multi-fill/stroke, dash/cap/join
are all modeled, editable per-entry, and rendered (SVG/PNG/editor). PDF is
solid-only by design.

---

## 4. IMAGE + CROP — the important one

### Image model
`NodeKind::Image(ImageNode)` (`scene.rs:331`, `ImageNode` at `scene.rs:430-434`)
carries only `asset_id: AssetId` and `alt: Option<String>`. **All visual
placement/crop intent lives on the node's `asset_placement`, not on `ImageNode`.**

`AssetPlacement` (`assets.rs:328-338`):
```
pub struct AssetPlacement {
    pub fit: Option<ImageFitMode>,            // Contain | Cover | Crop
    pub focal_point: Option<FocalPoint>,      // { x: f64, y: f64 } in 0..1
    pub preserve_transparency: Option<bool>,
    pub alt_text: Option<String>,
}
```
`ImageFitMode` = `Contain | Cover | Crop` (`slots.rs:172-178`).
`FocalPoint` = `{x, y}` normalized 0..1 (`slots.rs:180-184`).

### >>> THERE IS NO STORED CROP RECT. <<<
Crop is **derived**, not stored. I grepped the whole `crates/` tree for any
`crop_rect`/`CropRect`/`crop_x`/`crop_window`/`object_position` style field —
none exist (only the word "crop" inside fit-mode logic). The crop window is
COMPUTED at render time by `focal_crop_geometry` from three inputs:
`fit ∈ {Cover, Crop}`, `focal_point`, and the asset's **natural aspect ratio**.

`focal_crop_geometry` (`svg.rs:1032-1072`):
- Requires `placement.focal_point` AND `fit ∈ {Cover|Crop}` (else `None`,
  `svg.rs:1038-1045`).
- Requires the asset record's `natural_aspect_ratio()` (`svg.rs:1049`) — pulled
  from raster pixel dims / logo / vector metadata (`assets.rs:57-71`).
- Scales the drawn image to cover the box, then offsets it so the focal point
  sits as near box-center as the image allows (`svg.rs:1054-1064`), returning a
  `FocalCropGeometry{x,y,width,height}` (the image draw rect, possibly negative
  origin), clipped to the node box.

This same function is the single source of truth shared by:
- **SVG export**: `render_image_node` calls it at `svg.rs:554`, emits a
  `<g clip-path…><image preserveAspectRatio="none" …/></g>` with the computed
  window (`svg.rs:564-575`). Non-focal fits map to `preserveAspectRatio`
  (`image_preserve_aspect_ratio` `svg.rs:1077-1086`: cover/crop = `xMidYMid slice`,
  contain = `xMidYMid meet`).
- **PNG/Skia**: `paint_image` calls `focal_crop_geometry` at `render.rs:463`,
  clips to corner-rrect and draws the window (`render.rs:463-479`). The
  non-focal fallback re-derives cover/contain from the decoded intrinsic ratio
  (`render.rs:481-522`); SVG byte assets render via `skia_safe::svg::Dom`
  (`render.rs:543-577`).

### Where crop intent gets set today (NOT the DSL)
- **DSL cannot author fit/focal**: `img`/`image` only accepts an asset id
  (`dsl.rs:2895-2920`). I grepped `dsl.rs` for `fit`/`focal`/`cover`/`contain`/
  `crop`/`AssetPlacement` — no authoring syntax exists. So the agent's DSL text
  cannot directly express a crop; placement is set programmatically.
- **Programmatic placement**: `Operation::PlaceAssetInNode` /
  `PlaceAssetInSlot` (`operations.rs:174-182`). `place_asset_in_node`
  (`operations.rs:599-670`) sets `node.kind = Image`, `source_asset_id`, and
  `node.asset_placement = Some(placement)` (`operations.rs:622-630`).
- **Slot policy**: `ImagePolicy` (`slots.rs:163-170`) also carries
  `fit/focal_point/aspect_ratio/min_dpi/preserve_transparency`; slot validation
  warns when `fit == Crop` without a focal point (`assets.rs:851-858`) and
  blocks crop when the license forbids modification (`assets.rs:880-890`).
- **Edit op**: `NodeEditPatch.asset_placement: OptionalFieldPatch<AssetPlacement>`
  (`editing.rs:591`) and `image_asset_id` (`editing.rs:594`) — so changing the
  image and its fit/focal IS an editable patch path today
  (`editing.rs:928-946`).

### Editor preview does NOT render images or crop
`renderAdapter.ts:232-242` puts only `assetId/sourceAssetId/alt/label/kind/status`
into the descriptor — **no fit, no focal, no asset bytes**. The CanvasKit
renderer explicitly draws images as their placeholder fill: "Images draw as
their placeholder fill (no asset bytes in the descriptor yet)"
(`drawDescriptors.ts:16-17`). Real pixels + crop only appear in PNG/SVG export.

### Verdict on crop
- **Fit (contain/cover/crop) + focal-point crop EXISTS** and is renderable
  (SVG, PNG) and editable (patch). This covers "reposition the visible region
  by moving a focal point" and "switch contain/cover/crop".
- **A free-form rectangular crop (drag crop handles to an arbitrary window) is
  MISSING.** There is no stored crop rect; the window is a pure function of
  fit+focal+natural-ratio. To support "crop image" as a designer expects
  (independent of aspect ratio, arbitrary inset on all four sides), a new
  stored field (e.g. a normalized crop `Rect` on `AssetPlacement`) plus
  renderer support in both SVG and Skia would have to be BUILT.
- **PDF renders no images at all**: `NodeKind::Image(_) => warn_unsupported`
  (`pdf.rs:286`). So crop/image is moot for PDF.
- **Shape crop / clipping**: there is a `clip: bool` on containers
  (`scene.rs:291`) honored by Frame/AutoLayout in SVG (`svg.rs:279-315`) and
  Skia (`render.rs:215-224`, `clip_rrect`). That clips children to the
  container's rounded-rect — it is NOT an arbitrary vector clip mask. "Crop a
  shape to an arbitrary path" is **MISSING**.

---

## 5. The render contract: what a node must have to render, and the
##    freehand/absolute question

### The geometry contract
Both the Rust exporters and the editor preview resolve a node's render box the
same way, via `render_box_for_node` (`render_geometry.rs:22-45`):

```
if let Some(computed) = &node.computed {        // PREFERRED
    x = computed.layout_bounds.x  (minus parent origin)
    y = computed.layout_bounds.y  (minus parent origin)
    width/height = computed.layout_bounds.{w,h}
} else {                                          // FALLBACK
    x = node.transform.x
    y = node.transform.y
    width/height = node.size  (Fixed only; Hug/Fill/Token => 0.0)
}
```
`node_render_size` (`render_geometry.rs:11-20`) and `dimension_value`
(`render_geometry.rs:47-52`) confirm: when `computed` is absent, only
`Dimension::Fixed` yields a real size — Hug/Fill/Token collapse to 0.

So the render contract is: **a node renders correctly if EITHER (a) it has
`computed.layout_bounds` (the normal path — the layout engine relays out on
load), OR (b) it has a `Fixed` size and the `transform.x/y` is its true
parent-relative position.**

### Does freehand/absolute have a render path? — YES, with a caveat
There is a real fallback render path that uses `transform.x/y` + `size`
directly when `computed` is `None` (`render_geometry.rs:38-44`). An
absolutely-positioned, fixed-size node with no `computed` renders at its
transform. **This is exactly the shape a freehand-edited node would take.**

Caveats / what makes it fragile:
1. **`computed` shadows `transform`.** If `computed` is present (the normal
   state after layout), render IGNORES `transform.x/y` entirely
   (`render_geometry.rs:23-36`). The layout engine writes `computed` for every
   node on load. So a freehand drag that only mutates `transform` would be
   *overwritten/ignored* unless either (a) layout is re-run to fold the new
   position into `computed`, or (b) `computed` is cleared and the node is given
   a `Fixed` size. The user's "prior attempt failed because positions are
   solved" pain is exactly this shadowing.
2. **The editor preview's fallback is deliberately different from export.**
   `nodePositionForRender` (`renderAdapter.ts:487-517`): when `computed` is
   absent AND the node is layout-managed (auto-layout child), it renders at
   `(0,0)` relative to parent, NOT at `transform` (`renderAdapter.ts:510-512`),
   because for a flow child `transform` is meaningless. For non-layout-managed
   nodes it uses `transform` (`renderAdapter.ts:513-516`). This already encodes
   a "freehand vs layout-managed" distinction in the preview.
3. **Hug/Fill without `computed` is a loud error**, not a silent zero: SVG/PNG
   emit `LUME0205` ("hug/fill sizing without resolved export geometry",
   `svg.rs:1092-1109`) and auto-layout without `computed` emits `LUME0201`
   (`svg.rs:270-277`). So intrinsic-sized nodes MUST be solved before export.

### Existing "freehand-ness" hooks
The editor already distinguishes managed vs free nodes:
- `isNodeLayoutManaged` (`sceneQueries.ts:172-181`): true only when the parent
  node's kind is `auto_layout`. A node that is a direct child of a *page* or of
  a *frame/group* is therefore NOT layout-managed by this definition.
- `isNodeDirectGeometryEditable` (`sceneQueries.ts:183-192`): editable iff not
  layout-managed and not `locked`. This is the existing gate the canvas uses to
  decide whether a node can be dragged/resized directly.

So a "freehand mode" toggle has a natural home: a node under a page/frame
(not under auto_layout) is already directly geometry-editable, and the render
fallback already supports `transform`-based positioning when `computed` is
cleared.

---

## 6. Assets pipeline (as it bears on crop)

- **Bytes never live in the Scene.** `AssetRecord` (`assets.rs:17-40`) is
  metadata + an opaque `AssetLocation{provider, opaque_ref, url}`
  (`assets.rs:195-200`). The scene holds `assets: BTreeMap<AssetId, AssetRecord>`
  (`scene.rs:20`). Stated boundary: `lumen-assets/src/lib.rs:6-11` and
  `resolver.rs:1-8`.
- **Resolution for export** goes through `AssetByteResolver`
  (`resolver.rs:49-51`); `FixtureAssetResolver` for tests
  (`resolver.rs:57-134`); a store-backed resolver composes lumen-assets'
  `AssetStore`. The Skia renderer resolves via `resolve_image_bytes`
  (`render.rs:609-661`), emitting `LUME0202` (no resolver), `LUME0211` (no
  record), `LUME0210` (resolve error).
- **Ingest** (`ingest.rs:87-235`): size cap (`DEFAULT_MAX_BYTES = 10 MiB`,
  `ingest.rs:17`), MIME sniff, SVG sanitization (`ingest.rs:169-196`), raster
  probe + thumbnail (`ingest.rs:197-224`). Raster probe fills
  `RasterAssetMetadata{pixel_width, pixel_height, dpi, has_alpha, aspect_ratio}`
  (`assets.rs:202-211`). **This pixel-size metadata is the `natural_aspect_ratio`
  that focal-crop math depends on** (`assets.rs:57-71`, `svg.rs:1049`).
  Implication: a free-form crop feature would also want the natural pixel size
  (already available) to translate a normalized crop rect into the source.
- **Licensing gates crop**: `validate_placed_asset_license` blocks crop when
  `!asset.allows_modification()` (`assets.rs:880-890`, code `LUMA0401`).

---

## 7. Editing implications & round-trip

### What is "expose existing" vs "build new"
| Property the user wants to edit | Modeled? | Renderable (SVG/PNG)? | Edit-patch path? | Verdict |
|---|---|---|---|---|
| Opacity | Yes (`scene.rs:284`) | Yes (`svg.rs:255`, `render.rs:202-210`) | Yes (`editing.rs:586`) | **Expose existing** (PDF lacks it) |
| Recolor (solid/gradient) | Yes (`scene.rs:651-672`) | Yes (`render.rs:792-868`) | Yes per-fill (`editing.rs:580`) | **Expose existing** |
| Strokes (width/dash/cap/join/align) | Yes (`scene.rs:558-574`) | Yes (`render.rs:732-788`) | Yes (`editing.rs:582`) | **Expose existing** |
| Image swap | Yes (`ImageNode`, `operations.rs:599`) | Yes (`render.rs:441-523`) | Yes (`editing.rs:594`) | **Expose existing** |
| Image fit (contain/cover/crop) | Yes (`AssetPlacement.fit`) | Yes | Yes (`editing.rs:591`) | **Expose existing** |
| Focal-point crop | Yes (`AssetPlacement.focal_point`) | Yes (`focal_crop_geometry`) | Yes (`editing.rs:591`) | **Expose existing** |
| **Free-form rectangular crop** | **No stored crop rect** | derived only | n/a | **BUILD NEW** (new field + renderer in svg.rs & render.rs) |
| **Arbitrary shape/path crop mask** | only container `clip:bool` rrect (`scene.rs:291`) | rrect clip only | `clip` patch (`editing.rs:588`) | **BUILD NEW** for arbitrary masks |
| Per-fill opacity (separate from color alpha) | No (`dsl.rs:4527-4536` rejects `solid(c,opacity)`) | n/a | n/a | **BUILD NEW** (or use color alpha / node opacity) |
| Image rendering in editor preview | descriptor lacks bytes/fit (`renderAdapter.ts:232-242`, `drawDescriptors.ts:16-17`) | placeholder fill only | n/a | **BUILD NEW** (editor image draw) |
| Image/gradient/opacity in PDF | unsupported (`pdf.rs:286, 404`) | no | n/a | out of scope / **BUILD NEW** |

### The round-trip question (human freehand edit → agent resumes)
The render contract makes the round-trip tractable for the *visual* properties
in this subsystem, because every one of opacity/color/stroke/effect/fit/focal is
a plain, serialized field on the node with an inverse-able patch path
(`operations.rs` builds inverse operations, e.g. `editing.rs:1118-1119`,
`operations.rs:1275`). A human edit to any of these is just a field change; the
agent re-reads the same `Scene` and can patch it again. No representational gap.

The genuinely hard part is GEOMETRY, and it surfaces directly in this
subsystem's render contract:
- The renderer prefers `computed.layout_bounds` over `transform`
  (`render_geometry.rs:22-36`). The layout engine writes `computed` for every
  node and relays out on load (`renderAdapter.ts:502-509` comment). So a
  freehand drag that mutates only `transform` is invisible to render until
  either layout reruns (folding the new transform into `computed`) or `computed`
  is cleared and the node is given a `Fixed` size.
- For the AGENT to "take back" a freehanded node, the scene must record enough
  to know the node is now free: the cleanest representation is the node being a
  child of a page/frame (not auto_layout) with a `Fixed` `SizeSpec` and a
  meaningful `transform` — exactly the state `isNodeLayoutManaged == false`
  already describes (`sceneQueries.ts:172-192`). Render already supports that
  state via the fallback path. **The missing piece is not in render/assets — it
  is in the layout/editing layer deciding when to clear `computed` / detach from
  flow / persist `transform`** (covered by the layout + editing subsystem maps,
  not this one).
- `render_bounds` (`scene.rs:707`, `layout.rs:1514-1558`) is derived from
  `layout_bounds` + transform, so it does not need separate round-trip handling.

### Concrete recommendations for the architects (this subsystem only)
1. **Crop**: introduce an explicit normalized crop rect on `AssetPlacement`
   (e.g. `crop: Option<Rect>` in 0..1 source-space) and have BOTH
   `focal_crop_geometry`/`paint_image` (`render.rs:441-523`) and
   `render_image_node` (`svg.rs:529-…`) honor it. Keep fit+focal as the
   higher-level convenience; the explicit rect is the freehand power-tool. The
   asset's natural pixel size needed to map it is already ingested
   (`assets.rs:202-211`).
2. **Per-fill opacity**: either finish the `solid(color, opacity)` lowering the
   DSL stubs out (`dsl.rs:4533`) or rely on color alpha; the renderers already
   handle `#RRGGBBAA` (`render.rs:993-1002`).
3. **Editor image preview**: thread asset bytes + `asset_placement` into
   `RenderNodeDescriptor.image` (`renderAdapter.ts:232-242`) and draw the real
   image with the same `focal_crop_geometry` math so the editor preview matches
   export. Today it is placeholder-only (`drawDescriptors.ts:16-17`), which
   means a human cropping an image would see no live feedback.
4. **Geometry round-trip is owned elsewhere** — render/assets already supports a
   `transform`+`Fixed`-size freehand node; the work is in layout/editing.

### Caveats on what I did NOT verify
- I did not trace the brand/token resolver that turns `Color::Token` /
  `opacity_token` into concrete values (lives in `brand.rs`, out of scope here).
- The PDF writer's full capabilities were sampled, not read end-to-end; the
  image/gradient/opacity gaps cited are from explicit `warn_unsupported` /
  `Unsupported` sites (`pdf.rs:286, 404, 414`).
- I confirmed the editor CanvasKit image-placeholder behavior from the
  drawDescriptors header comment and the descriptor shape, not by reading every
  branch of `drawDescriptors.ts`.
