# Phase F Parity And Acceptance Matrix

Date: 2026-06-11

Branch: `phase-f/editor-export-productization-v0`

This document is the working acceptance matrix for Phase F. It maps canonical
scene/export fields to the editor canvas, SVG/PNG/PDF export paths, user-facing
diagnostics, and tests. It is intentionally evidence-based: a field is not
treated as complete unless a current implementation and test or conformance
check proves the behavior.

## Parity Rule

The Phase F source-of-truth path is:

```text
Scene + Operation
  -> checked apply
  -> preflight
  -> computed geometry / token resolution / diagnostics
  -> editor render descriptors
  -> Konva canvas view

Scene + Operation
  -> checked apply
  -> preflight
  -> computed geometry / token resolution / diagnostics
  -> ExportRequest
  -> SVG / PNG / PDF artifacts + sidecars
```

Konva is a view. Export artifacts are outputs. Neither is allowed to become a
second design model.

## Field Matrix

| Canonical Field Or Behavior | Editor/Konva | SVG Export | PNG Export | PDF Export | Current Evidence | Status |
| --- | --- | --- | --- | --- | --- | --- |
| Custom page width/height/unit | Canvas descriptor and fit/zoom use `PageSize` directly. | SVG `width`, `height`, and `viewBox` use canonical dimensions. | Raster dimensions derive from page size and profile scale/DPI. | PDF MediaBox derives from page size, with optional bleed expansion. | `exportParity.test.ts`, `renderAdapter.test.ts`, `export_adapter.rs`, `phase_f_manifest.json`, API export tests. | Proven for current custom-size fixture set. |
| Presets as shortcuts only | Page rail/inspector can use presets but stores editable canonical size fields. | Export consumes page dimensions, not preset capability checks. | Same as SVG. | Same as SVG/PDF. | `EditorApp.test.tsx`, `exportParity.test.ts`, `phase_f_manifest_page_sizes_export_with_canonical_dimensions`. | Proven for F1/F1a coverage set. |
| Page background | Canvas renders page background from scene fills. | SVG paints page background. | PNG rasterizes SVG baseline. | PDF paints page background. | `renderAdapter.test.ts`, `export_adapter.rs` PDF background test. | Proven for solid fills; gradients are an approximation warning in editor. |
| Bleed and safe area | Canvas overlays show bleed/safe-area guides and page center guides. | SVG trim export remains scene page unless profile changes. | PNG follows exported page artifact. | Print profile can include bleed in PDF MediaBox and offsets trim content. | `EditorApp.test.tsx`, `CanvasSurface.tsx`, `export_adapter.rs` bleed tests. | Proven for visible guardrails and PDF bleed expansion. |
| Node child order | Layer panel and render descriptors follow page/container child arrays. | SVG emits children in scene order. | PNG rasterizes SVG order. | PDF walks page children in order. | `LayerPanel` via `EditorApp.test.tsx`, `export_adapter.rs`, `renderAdapter.test.ts`. | Proven for current node kinds. |
| Computed geometry | Canvas/render descriptors prefer computed bounds for layout-managed nodes. | SVG uses computed coordinates for layouted nodes. | PNG rasterizes computed SVG baseline. | PDF uses computed coordinates. | `renderAdapter.test.ts`, `exportParity.test.ts`, `export_adapter.rs` computed-geometry tests. | Proven. |
| Non-visual groups | Group nodes without fills remain non-visual containers in canvas descriptors. | SVG exporter does not invent group backgrounds. | PNG follows SVG. | PDF follows node draw behavior. | `renderAdapter.test.ts`, earlier editor review fixes. | Proven for fill-less groups. |
| Free-position move/resize | Canvas emits structured operations for safe nodes; disabled states explain locked/layout-managed nodes. | Export consumes updated scene after operation/preflight. | Same as SVG. | Same as SVG. | `canvasOperations.test.ts`, `canvasSelection.test.ts`, `EditorApp.test.tsx`. | Proven for fixed-size common nodes. |
| Auto-layout controls | Inspector/layers expose direction, gap, padding, alignment, wrap, child order, and layout-managed affordances. | Export consumes recomputed layout geometry. | PNG follows SVG. | PDF follows computed geometry. | `InspectorPanel.test.tsx`, `EditorApp.test.tsx`, `layout_engine.rs`. | Proven for controls/reorder; drag-insertion preview remains deferred. |
| Text content/style fields | Canvas renders content, family, size, weight, align, line-height, letter spacing, wrap, max lines, and direction as closely as Konva allows. | SVG uses measured lines and text metadata. | PNG rasterizes SVG baseline. | PDF uses measured text lines and warns on overflow/shaping limits. | `renderAdapter.test.ts`, `text_measure.rs`, `export_adapter.rs`, `renderDiagnostics.test.ts`. | Partially proven; advanced shaping/font embedding remains a known divergence. |
| Text overflow diagnostics | Inspector/validation/export surfaces show overflow diagnostics. | SVG/export diagnostics carry text issues. | PNG inherits export diagnostics. | PDF warns when text overflows render box. | `ValidationPanel`, `InspectorPanel`, `export_adapter.rs`, `EditorApp.test.tsx`. | Proven for current heuristic text measurement. |
| Fills/strokes/corner/opacity | Inspector exposes common fields and token-safe style controls. | SVG exports solid fills/strokes/radius/opacity. | PNG rasterizes SVG. | PDF supports solid fill/stroke basics. | `InspectorPanel.test.tsx`, `operations.test.ts`, `export_adapter.rs`. | Proven for solid/common fields; gradients are approximated in canvas. |
| Brand tokens | BrandKit panel and style inspector preserve token references and run governance/compatibility diagnostics. | Preflight resolves tokens before export when a BrandKit/default exists. | PNG follows resolved SVG. | PDF follows resolved scene and reports print limitations. | `BrandKitPanel`, `InspectorPanel`, `brand_tokens.rs`, API preflight/export tests. | Proven for current token carriers. |
| Slots | Slot inspector shows bound nodes, metadata, samples, fixture previews, and diagnostics. | SVG/sidecar preserves slot metadata. | PNG sidecar preserves slot metadata. | PDF sidecar preserves slot metadata. | `SlotInspector`, `InspectorPanel`, `export_adapter.rs`, API export tests. | Proven for current slot metadata; conditional/repeater runtime deferred. |
| Image/logo assets | Canvas uses placeholders and marks unresolved/missing assets. | SVG/PDF may show placeholders and sidecar asset refs until Phase E resolver exists. | PNG rasterizes SVG placeholder baseline. | PDF emits print DPI/missing metadata diagnostics. | `renderDiagnostics.test.ts`, `exportParity.test.ts`, `export_adapter.rs`. | Partial by design; real asset byte resolution is Phase E. |
| Vectors/SVG path data | Supported vector/path nodes render/export where current adapters support them; unsupported cases should surface diagnostics. | SVG has the stronger baseline. | PNG rasterizes SVG baseline. | PDF vector coverage is limited to supported primitive paths. | `renderAdapter.test.ts`, `export_adapter.rs`. | Partial; full vector editing is out of Phase F scope. |
| Export profiles | Export panel exposes SVG, PNG, PDF, preview, high-res PNG, and print PDF profiles; profiles can be saved/removed through operations. | Profile controls adapter behavior. | Profile scale/DPI controls raster output. | Profile intent/bleed/font flags control PDF diagnostics and MediaBox. | `ExportPanel`, `exportRunner.test.ts`, `EditorApp.test.tsx`, API tests. | Proven for current profiles. |
| Export artifact identity | UI/API preserve filenames, sidecar filenames, dimensions, byte counts, page ids, and sidecar summaries. | SVG artifacts include text and sidecar JSON. | PNG artifacts include data URL and dimensions. | PDF artifacts include data URL, dimensions, sidecar JSON. | `ExportPreviewSurface.test.tsx`, `exportRunner.test.ts`, API tests. | Proven. |
| Export preview approval | Preview surface derives fail-closed readiness from artifact presence, export status, parity result, and diagnostics. | N/A | N/A | N/A | `exportPreviewApproval.test.ts`, `ExportPreviewSurface.test.tsx`. | Proven for UI/agent-shared helper. |
| Export parity diagnostics | Preview compares active-page canvas size, export dimensions, sidecar node ids, SVG node ids/text, unresolved tokens, and asset placeholders. | SVG text and sidecar are inspected. | PNG sidecar and dimensions are inspected. | PDF dimensions are compared through MediaBox-derived metadata. | `exportParity.test.ts`, `ExportPreviewSurface.test.tsx`. | Proven for current parity categories. |
| Print guardrails | Editor shows readiness warnings; PDF exporter emits diagnostics for fonts, bleed, safe area, pagination, DPI, RTL/non-Latin, and required slot safe area. | N/A | N/A | PDF diagnostics and MediaBox behavior are tested. | `ExportPanel.tsx`, `export_adapter.rs`, API tests. | Proven as guardrails, not final print fidelity. |

## Known Divergences

These are explicit product limitations, not hidden behavior.

| Divergence | Current Behavior | Product Impact | Owner / Later Phase |
| --- | --- | --- | --- |
| Advanced text shaping and font embedding | Canvas/PDF warn for non-LTR, non-Latin, max-line, and font embedding limits. PDF uses early built-in-font path. | Print output is not final-production typography for complex scripts or licensed fonts. | Print fidelity track after Phase F. |
| Real asset byte resolution | Editor/export can show placeholders and asset metadata but does not own upload/storage/provider byte resolution. | User can inspect placement but not final image/logo fidelity without Phase E runtime. | Phase E asset runtime/export resolver. |
| Full vector editing | SVG/export can preserve supported vector data; editor does not provide Figma-grade vector editing. | Users cannot deeply edit arbitrary vector paths yet. | Later editor/vector track. |
| Auto-layout drag insertion preview | Reorder and layout controls exist; drag insertion math is not fully productized. | Users can reorder safely through controls but not yet with polished Figma/Brilliant-style insertion gestures. | Core layout/editor helper follow-up. |
| Pixel-perfect visual snapshots | Geometry/content/metadata conformance is covered; pixel baselines are still limited. | Drift can still occur in typography/assets where fonts/runtime are unstable. | Visual regression hardening after asset/font runtime stabilizes. |

## Acceptance Status

| Phase F Gate | Evidence | Status |
| --- | --- | --- |
| Canvas and SVG export agree on custom-size page dimensions. | `exportParity.test.ts`, `phase_f_manifest.json`, `export_adapter.rs`. | Proven for square, wide, tall, email, and A4 fixtures. |
| Custom dimensions are editable and preserved through preflight/export. | `PageRail`, `InspectorPanel`, `EditorApp.test.tsx`, API preflight/export tests. | Proven for current UI/API flows. |
| Presets are shortcuts, not renderer/export constraints. | Manifest custom cases and tests use explicit `PageSize` dimensions. | Proven for current paths. |
| Canvas/export use computed geometry for layouted nodes. | `renderAdapter.test.ts`, `layout_engine.rs`, `export_adapter.rs`. | Proven. |
| Selection, move, resize, reorder, and undo flows work. | `canvasOperations.test.ts`, `EditorApp.test.tsx`, `LayerPanel`. | Proven for common nodes and reorder controls. |
| Auto-layout state is inspectable and adjustable. | `InspectorPanel.test.tsx`, `EditorApp.test.tsx`. | Proven for controls; drag insertion deferred. |
| Slots are visible and previewable. | `SlotInspector`, `InspectorPanel.test.tsx`, export sidecar tests. | Proven for current slot contract. |
| BrandKit/style state is visible and editable through token-safe controls. | `BrandKitPanel`, `InspectorPanel.test.tsx`, brand governance tests. | Proven for current token carriers. |
| Export profiles for SVG, PNG, PDF, print, and preview exist. | `ExportPanel`, `exportRunner.test.ts`, API tests. | Proven. |
| Export readiness diagnostics are visible. | `ExportPanel`, `ExportPreviewSurface`, `ValidationPanel`, tests. | Proven. |
| Visual/export conformance covers branded/slotted/custom-size fixtures. | `phase_f_manifest.json`, editor parity tests, export adapter tests. | Proven at geometry/metadata/content level; pixel snapshots remain limited. |
| Print limitations are diagnostics. | `ExportPanel`, `crates/lumen-export/src/pdf.rs`, export adapter tests. | Proven as guardrails. |
| React/Konva does not fork design semantics. | Editor operations/tests emit canonical operations; render descriptors are views. | Proven for implemented edit flows; maintain as invariant. |

## Phase F Completion Evidence

- Canvas, export preview, and split compare modes are implemented in the editor
  product surface.
- Export preview has a fail-closed approval readiness summary derived from the
  canonical export/parity result.
- Full editor verification has passed: lint, tests, and production build.
- Full Rust workspace verification has passed: `cargo test`,
  `cargo clippy --all-targets -- -D warnings`, wasm check, and the ignored
  visual regression skeleton.
- API export/preflight tests have passed against the compact artifact and
  document export routes.

## Post-Phase F Hardening

These items should continue after Phase F but are not required for this phase's
first usable product surface:

- Harden pixel or screenshot-based regression once fonts/assets are stable
  enough to make baselines meaningful.
- Replace asset placeholders with real byte resolution after Phase E asset
  runtime lands.
- Add final font embedding/subsetting, bidi shaping, and print-house-specific
  PDF conformance in the later print-fidelity track.
- Add polished drag-insertion previews for auto-layout children after core
  insertion-index helpers are available.
- Keep the known divergence list current whenever a field is intentionally
  approximate in canvas or export.
