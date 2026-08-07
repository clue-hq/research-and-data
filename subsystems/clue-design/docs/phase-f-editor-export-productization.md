# Phase F: Editor And Export Productization

Date: 2026-06-11

Branch: `phase-f/editor-export-productization-v0`

Worktree:
`/Users/aryankeshri/Documents/brilliant-design/phase-f-editor-export-productization-v0`

Baseline: `9233596 Wire editor BrandKit compatibility runner`

Current acceptance matrix:
`docs/phase-f-parity-acceptance-matrix.md`

## Purpose

Phase F turns the design engine into a usable design product surface. The goal
is no longer only "the agent can compile and export something." The goal is that
a real user can inspect, correct, approve, and export the generated artifact
without leaving the product.

The editor must render the canonical `Scene` accurately enough that the user can
trust what they see. The SVG/PNG/PDF exports must consume the same scene,
computed geometry, brand/token resolution, slots, page dimensions, and export
profiles. The editor is allowed to own interaction state, but it must not own
design semantics.

## Dependency Position

Phase F can start before Phase D and Phase E.

Phase D, targeted editing and repair semantics, is useful but not required for a
human editor because the editor can emit canonical structured operations
directly. The missing Phase D DSL modify language mostly affects agent repair
ergonomics, not the basic ability for a human to select, drag, resize, inspect,
and export.

Phase E, asset runtime and creative tools, is useful but not required for editor
and export productization if Phase F uses existing fixture/metadata asset refs
and clearly marks unresolved assets in preview/export. Real uploads, byte
storage, image generation, SVG sanitization, and asset library UX should remain
Phase E work.

Phase F must not pretend D/E capabilities are complete. It should create stable
ports for them:

- editor actions emit canonical operations now, and later agent/DSL edit tools
  can reuse those operations;
- image/logo nodes render fixture or placeholder previews now, and later asset
  resolvers can supply real bytes;
- export profiles exist now, and later asset/font runtime can improve fidelity
  without changing scene semantics.

## Reference Gap Links

This phase addresses the following gaps from
`reference_docs/Brilliant-vs-Lumen-Product-Gap-Analysis.md`:

- Product Improvement Plan: Rendering/Export/Preview, Source Of Truth, Layout,
  Text, Text Measurement, Assets And Imagery.
- Layout Engine Comparison: editor parity, drag/reorder, computed geometry, and
  live layout feedback gaps.
- Text And Typography Comparison and Text Measurement: preview/export mismatch
  and print-grade text fidelity gaps.
- Scene Model Comparison: editor gestures, export profiles, and previews must
  consume canonical scene data.

It also follows the ABM spec's renderer boundary:

```text
Scene model
  -> renderer adapter interface
      -> React-Konva renderer for V1 editor
      -> SVG renderer/exporter for V1 export baseline
      -> future Vello/WebGPU renderer
      -> future Figma importer/exporter
```

React-Konva may own selection visuals, handles, drag/resize interaction, hover
state, pan, and zoom. React-Konva must not own slot semantics, canonical node
IDs, export settings, brand token resolution, template finalization, or
operation history.

## Product Outcome

By the end of Phase F's first useful version, a user should be able to:

1. Open a generated design document.
2. See every page/artboard at its real dimensions, including arbitrary custom
   sizes that are not in any preset catalog.
3. Select a node and understand what it is.
4. Move and resize common nodes.
5. Reorder nodes inside a page or auto-layout container where safe.
6. Edit basic text and style fields through inspectors.
7. Inspect slots, BrandKit state, validation, and export readiness.
8. Compare the editable canvas against the export preview.
9. Export SVG, PNG, and PDF from named profiles.
10. Trust that editor preview and export are derived from the same scene.

The product does not need to become Figma in this phase. It does need to support
the common approval and correction workflows for ABM artifacts.

## Source Of Truth Rules

Phase F must preserve these invariants:

- `Scene` is the canonical design model.
- `Operation` is the canonical mutation/history surface.
- Preflight computes/resolves layout, brand tokens, text measurement, and
  diagnostics before export or final approval.
- The editor displays the scene and emits operations. It does not mutate hidden
  local design semantics.
- Export adapters consume the same scene and computed geometry as the editor.
- If editor preview and export disagree, the export/SVG preview is treated as
  the fidelity baseline until the renderer adapter is fixed.

## Custom Artifact Size Requirement

The editor and export product must support arbitrary valid artifact dimensions.
Presets are shortcuts, not constraints.

Implementation must be custom-size-first. Editor code should not branch on
specific preset names to decide whether a page can be displayed, edited,
preflighted, or exported. Presets may provide initial width, height, unit,
orientation, bleed, and safe-area defaults, but after creation the canonical
`PageSize` values are the authority. A user or agent must be able to create and
continue editing many different custom artifact shapes without the product
treating them as exceptional cases.

This is a hard Phase F requirement because the product must support artifacts
such as square social ads, leaderboard ads, email headers, postcards, slide
covers, report pages, print mailers, and custom client-specific surfaces. The
editor must not force every design into A4, letter, or a small list of known
presets.

Phase F should be evaluated as a custom-artboard editor, not as a preset editor.
Any place that displays, edits, validates, previews, exports, or compares a
page/artboard must consume the page's canonical width, height, and unit. A
fixed preset catalog may exist only as a convenience menu for common sizes. It
must never be the source of truth, the capability boundary, or the fallback
path for rendering.

The canonical size rule is:

```text
Scene.pages[page_id].size
  -> editor page/artboard bounds
  -> preflight/layout coordinate space
  -> SVG viewBox and dimensions
  -> PNG raster dimensions / scale
  -> PDF page dimensions
  -> future HTML/CSS and Figma export dimensions
```

Required behavior:

- `PageSize { width, height, unit, preset: Custom }` must be treated as a
  first-class page/artboard size.
- The editor must support creating, opening, inspecting, editing, previewing,
  and exporting custom-sized artifacts directly from the page/artboard model.
  A custom artifact must not require an inner frame that pretends to be the real
  output size.
- Custom size support means any valid rectangular artifact size, not only the
  currently tested square ad size. The editor must support wide, tall, square,
  print, email, presentation, and client-specific artboards from the same scene
  `PageSize` contract.
- Canvas zoom, pan, and fit-to-screen behavior may scale the viewport for user
  comfort, but must never rewrite or normalize the canonical page dimensions.
- Preset pages must continue to work, but they must lower into the same
  `PageSize` contract as custom pages.
- Preset names must not be used as renderer/export capability checks. The
  capability check is whether the scene contains valid finite page dimensions
  and supported units.
- New-document, new-page, duplicate-page, and resize-page flows must all allow
  explicit custom dimensions. No creation path may require the user or agent to
  pick from a preset before they can produce a valid artifact.
- The editor must allow viewing and editing documents whose page dimensions are
  not in any preset list.
- The page/artboard inspector must expose explicit width, height, and unit
  controls for arbitrary custom sizes. Preset pickers may prefill those fields,
  but the user or agent must be able to override them without falling back to a
  fixed preset catalog.
- The editor must never coerce a custom page to the nearest preset, silently
  substitute A4/letter/default dimensions, or render a custom inner frame as a
  workaround for a missing page size.
- Export adapters must honor valid scene page dimensions exactly.
- Validation may reject invalid dimensions, such as zero, negative, non-finite,
  or unsafe raster sizes, but it must not reject dimensions merely because they
  are not presets.
- UI controls may offer common presets for convenience, but must also offer
  explicit custom width, height, and unit fields.
- The square-ad failure is considered fixed only when a 1080x1080 scene renders
  as 1:1 in canvas preview, SVG export, PNG export, and PDF/export-preview
  metadata.
- The broader custom-size requirement is considered fixed only when at least
  these non-preset dimensions can be opened, edited, previewed, and exported
  without fallback: `1080x1080`, `1200x628`, `1080x1350`, `600x800`, and one
  print/mail surface with bleed and safe-area guides.
- The editor must also remain usable when switching between materially
  different aspect ratios in the same document, for example a square ad, a wide
  email header, a vertical story/poster, and a print mailer. Page rail,
  inspector, canvas fit, pan, zoom, selection, drag/resize, export preview, and
  parity diagnostics must all respond to each page's own dimensions.
- Custom-size tests should include square, wide, tall, small digital, large
  print, and mixed-document cases. A passing implementation cannot rely on
  hidden assumptions that only one custom shape, such as `1080x1080`, works.

Acceptance gate: Phase F is not complete if the editor or any export path only
works for a fixed preset catalog. A valid custom `PageSize` must be enough to
drive the artifact's canvas, interaction bounds, preview, and export output.
Preset-only behavior is a product blocker, even if the common preset examples
continue to pass.

## Current Starting Point

The baseline already has:

- React/Next editor shell.
- `react-konva` and `konva` dependencies.
- `CanvasSurface` and `renderAdapter` boundaries.
- Page rail, inspector, slot inspector, validation panel.
- BrandKit panel with governance and compatibility runner ports.
- Local editor operation application for common mutations.
- Export adapters for SVG, PNG, early PDF.
- Preflight pipeline with computed geometry.
- Layout/text reliability from Phase B.
- BrandKit/design-system maturity from Phase C.

The baseline is not yet productized because:

- canvas/export parity is not measured systematically;
- the editor does not expose enough direct manipulation controls;
- auto-layout interaction controls are thin;
- export profiles are not a first-class product UI/API surface;
- print fidelity remains incomplete;
- visual regression is still mostly skeleton-level;
- asset/font runtime is intentionally not production-grade yet.

## Scope Breakdown

### F0. Scope Lock And Parity Contract

Goal:

Define the exact contract between the editor canvas, computed scene geometry,
and export adapters.

Build:

- A renderer parity checklist for page size, transforms, computed bounds, fills,
  strokes, text, opacity, corner radius, images, vectors, slots, and metadata.
- A typed editor render descriptor that is intentionally close to export
  geometry, not a separate design model.
- A documented rule for fallback behavior when Konva cannot exactly match SVG.
- A custom-dimension parity rule proving arbitrary page sizes are not treated
  as preset-only exceptions.

Acceptance:

- The spec identifies which scene fields the editor must render now.
- Every known unsupported field is either hidden from editor mutation or shown
  with an explicit diagnostic/placeholder.
- The plan explains how parity is tested.
- Custom page/artboard dimensions are represented as canonical `PageSize`
  values, not renderer-local canvas dimensions.

### F1. Canvas Rendering Parity

Goal:

Make the React-Konva canvas show the same page dimensions and node geometry that
SVG export will use.

Build:

- Page/artboard rendering from `PageSize`, including arbitrary custom
  dimensions and units.
- Custom page-size controls that accept width, height, and unit without forcing
  a preset.
- Viewport fit, zoom, pan, selection, handles, and page rails must work from the
  actual `PageSize` rectangle for any valid aspect ratio. The editor must not
  assume a fixed canvas, A4-like page, social-post-only shape, or preset catalog
  when calculating interactive bounds.
- Preset UI is allowed only as a convenience layer that fills editable size
  fields. It must not be the only way to create or modify an artifact size.
- Node rendering from computed geometry when available, falling back to fixed
  transform/size only when computed geometry is absent.
- Parent-child drawing order matching scene/page child arrays.
- Non-visual group handling.
- Auto-layout node display using computed bounds.
- Text rendering with line-height, letter-spacing, wrap, max-lines, direction,
  and measured multiline behavior as closely as Konva allows.
- Image/vector placeholder rendering that preserves bounds, alt text, and asset
  IDs until Phase E supplies real bytes.
- Slot and semantic metadata overlays that do not alter the canonical scene.

Acceptance:

- A custom 1080x1080 document renders as a square in the editor.
- Non-preset custom pages, such as 1200x628, 1080x1350, 600x800, and print
  mailer sizes, render without being coerced to A4/letter/default dimensions.
- Very wide and very tall custom artifacts remain usable: the canvas can fit,
  pan, zoom, select, drag, and resize against the true page bounds without
  clipping because the size is not in a preset list.
- Users can change an existing page from one custom size to another through the
  editor inspector, and the canvas, export preview, and operation log all reflect
  the new canonical `PageSize`.
- Exported SVG `viewBox` and editor canvas bounds agree for the active page.
- Nodes with `computed.layout_bounds` are not collapsed or placed by stale fixed
  dimensions.
- Groups without fills remain non-visual.
- Text does not silently ignore wrap/line-height/letter-spacing fields.

#### F1a. Custom Artboard Product Surface

Custom dimensions are not only an export compatibility detail. They are a
first-class editor workflow.

Build:

- New page/artboard creation with explicit width, height, unit, safe area, and
  bleed fields.
- Page inspector controls that can resize any existing page to arbitrary valid
  dimensions without forcing a preset.
- Preset shortcuts that only prefill editable fields and then save the same
  canonical `PageSize` shape as manually entered dimensions.
- Mixed-document page rails and canvas fit behavior for pages with different
  aspect ratios in one document.
- Export-preview parity checks that compare the active page's editor bounds
  against the actual SVG/PNG/PDF artifact dimensions.
- Regression fixtures for square, wide, tall, small digital, print, and mixed
  custom-size documents.

Acceptance:

- A user can create a page with a custom size that is not in any preset list,
  add/edit content on it, duplicate it, resize it, preview it, and export it.
- Switching between different custom-size pages in one document updates canvas
  fit, selection bounds, safe-area guides, page inspector values, and export
  preview metadata from the selected page's canonical size.
- No editor, preflight, preview, export, or parity path uses preset name as a
  capability check. Valid finite page dimensions are sufficient.
- The product never asks the user or agent to create a fake inner frame merely
  to get a custom output size. The page/artboard itself is the output surface.

### F2. Selection, Handles, Drag, Resize, And Undo

Goal:

Support basic human correction without requiring regeneration.

Build:

- Stable selection by canonical `NodeId`.
- Canvas hit testing that maps Konva objects back to scene nodes.
- Resize handles for fixed-size nodes.
- Drag move for nodes that are safe to move.
- Undo/redo stack backed by operation history or local operation replay.
- Snap-to-page bounds and optional safe-area guides.
- Clear disabled states for nodes that cannot be moved/resized directly because
  they are auto-layout-managed.

Acceptance:

- Dragging a free-positioned node emits a structured operation.
- Resizing a fixed-size node emits a structured operation.
- Undo restores the previous scene.
- Selection clears or re-scopes when changing pages.
- The editor never mutates Konva-only geometry without updating the scene.

### F3. Auto-Layout Controls And Live Layout Feedback

Goal:

Expose the layout engine to users instead of forcing fixed coordinates.

Build:

- Inspector controls for auto-layout direction, gap, padding, wrap, alignment,
  and child sizing.
- Reorder controls for children inside pages/groups/auto-layout containers.
- Drag insertion indicators for auto-layout children where practical.
- Layout diagnostics shown near the affected node/container.
- "Managed by auto-layout" affordances for child nodes whose coordinates come
  from layout.

Acceptance:

- Changing auto-layout gap/padding/alignment emits canonical operations.
- Reordering siblings updates the scene child order and recomputes layout.
- The canvas shows computed layout changes after operation application.
- Users can distinguish fixed-position nodes from layout-managed nodes.

Note:

This does not require Phase D DSL edit directives. It can use structured
operations directly. Phase D can later expose the same edits to agents.

### F4. Slot Inspector And Content Preview

Goal:

Make semantic slots visible and practical for approval workflows.

Build:

- Slot list grouped by page and bound nodes.
- Slot key, content type, required/optional state, overflow policy, sample
  content, and fit diagnostics.
- Node-to-slot binding visibility on selection.
- Content preview for slot fixtures/sample content.
- Basic slot edit operations already supported by the core contract.

Acceptance:

- A user can select a slotted node and see its slot metadata.
- Missing required slots and overflow diagnostics are visible without reading
  raw JSON.
- Slot overlays never alter export output unless the user commits an operation.

### F5. Brand And Style Inspector

Goal:

Make BrandKit-backed styling usable by a non-engineer.

Build:

- Current BrandKit and mode display.
- Token picker for fills, strokes, type styles, spacing, radius, opacity, and
  layout gap/padding where supported.
- Brand governance action and diagnostics.
- Compatibility warning surface for newer BrandKit versions.
- Clear fallback labels when a field is raw/off-brand.

Acceptance:

- A user can apply a BrandKit token to a selected common field.
- Governance diagnostics point to visible nodes or document-level state.
- The editor does not copy token catalogs into scene JSON.

### F6. Export Product Surface

Goal:

Turn export from a developer adapter into a user-facing workflow.

Build:

- Export profile selector for SVG, PNG, PDF, print PDF, and preview PNG.
- Per-page and all-pages export selection.
- Named export profiles stored in scene/document metadata where appropriate.
- Export readiness diagnostics before download.
- Export artifact summary with format, page IDs, warnings, file size, and
  sidecar metadata.
- Bulk preview skeleton that can export all pages/templates but does not yet
  require Phase G personalization runtime.

Acceptance:

- A user can export SVG, PNG, and PDF from the editor/API product surface.
- Export uses preflighted scene geometry and BrandKit resolution.
- Export warnings are visible before the user downloads.
- Export output dimensions match page/artboard dimensions.
- Export does not substitute preset dimensions when the scene uses a valid
  custom page size.

### F7. Preview And Export Parity Mode

Goal:

Give users and agents a reliable way to compare editable canvas output with the
export baseline.

Build:

- "Canvas" view for interaction.
- "Export Preview" view rendered from SVG/PNG export artifact.
- Side-by-side or toggle comparison for active page.
- Parity diagnostics for page size mismatch, missing nodes, missing text,
  unresolved tokens, and asset placeholders.
- Optional pixel/snapshot comparison test harness for stable fixtures.

Acceptance:

- The user can open the export preview without leaving the editor.
- If Konva preview diverges, the discrepancy is visible and testable.
- Agent visual critique can use the same export preview users approve.

### F8. Visual Regression And Export Conformance

Goal:

Prevent editor/export drift from returning.

Build:

- Shared fixture manifest for square ad, email hero, one-pager section, report
  cover, multi-page document, slotted document, and brand-token document.
- SVG conformance assertions for dimensions, metadata, slot attributes, text,
  and resolved tokens.
- PNG smoke export tests.
- Early PDF structural tests.
- Editor render descriptor tests for the same fixtures.
- Pixel or image snapshot tests where stable enough.

Acceptance:

- CI can prove editor descriptors and export adapters agree on page/node bounds.
- The square-ad failure cannot regress silently.
- Computed geometry conformance is tested for editor and export.

### F9. Print Fidelity Track

Goal:

Make print/PDF export reliable enough for professional handoff, while clearly
separating what requires later font/asset runtime.

Build now:

- Bleed and safe-area visualization in editor.
- Export profile flags for print intent, bleed inclusion, crop/safe-area checks,
  DPI, and raster scale.
- PDF diagnostics for missing font embedding/subsetting support.
- Text overflow and non-Latin/RTL warning gates.
- Basic pagination readiness diagnostics for multi-page explicit documents.

Defer or isolate behind adapters:

- final font embedding/subsetting;
- real font loading/runtime validation;
- advanced text shaping, bidi, hyphenation, and script fallback;
- automatic pagination of flowed documents;
- production PDF/A or print-house-specific quality gates.

Acceptance:

- Print-related limitations are explicit diagnostics, not silent failures.
- Safe area and bleed are visible before export.
- PDF output does not claim print readiness when fonts/assets are unresolved.

## What Phase F Should Not Do

Do not implement:

- Phase D DSL modify language as part of this work;
- full agent targeted repair policy;
- Phase E upload/storage/provider asset runtime;
- full Figma-level vector editing;
- multi-user collaboration;
- plugin marketplace;
- complete component system;
- production font licensing workflow;
- full automatic pagination engine.

Those are real product needs, but mixing them into Phase F would delay the
urgent usability surface and blur ownership boundaries.

## Implementation Order

### Milestone F-A: Planning And Baseline Audit

- Create this planning document.
- Audit current editor/export capabilities.
- Identify parity gaps by fixture.
- Add workstream memory entry.

Exit:

- Phase F scope and non-scope are explicit.

### Milestone F-B: Canvas/Export Parity Foundation

- Stabilize render descriptors.
- Ensure computed geometry, custom page dimensions, and group behavior match
  export.
- Add descriptor/export conformance tests.
- Add active page export preview surface.

Exit:

- The same tokenized square fixture has matching editor bounds and SVG export
  dimensions.

### Milestone F-C: Direct Manipulation MVP

- Selection and hit testing.
- Reordering the layers
- Drag/move.
- Resize fixed nodes.
- Undo/redo.
- Page switching and page-safe selection.

Exit:

- A user can make common corrections without writing DSL.

### Milestone F-D: Inspectors And Layout Controls

- Slot inspector improvements.
- Brand/style inspector improvements.
- Auto-layout controls and reorder actions.
- Validation and governance diagnostics placed in the product UI.

Exit:

- A user can understand and adjust semantic/layout/style state from the editor.

### Milestone F-E: Export Product Surface

- Export profile UI/API.
- SVG/PNG/PDF download or artifact generation.
- Export readiness diagnostics.
- Export preview comparison mode.

Exit:

- A user can approve from preview and export usable artifacts.

### Milestone F-F: Print Fidelity Guardrails

- Bleed/safe-area overlay.
- Print profile diagnostics.
- PDF quality checks for known limitations.

Exit:

- Print output has visible constraints and honest diagnostics.

## Test Plan

Run and expand these suites as implementation proceeds:

- `npm test` in `apps/editor`
- `npm run lint` in `apps/editor`
- `npm run build` in `apps/editor`
- `cargo test -p lumen-core`
- `cargo test -p lumen-export`
- `cargo test --test visual_regression -- --ignored`
- `cargo test -p lumen-api-helper`
- `.venv/bin/python -m pytest apps/api/tests`
- parity-specific editor/export fixture tests added in this branch

The key Phase F tests should prove:

- custom page dimensions are honored by editor and export;
- arbitrary valid non-preset dimensions do not fall back to A4/letter/default
  sizes;
- computed geometry is used by editor and export;
- selection/drag/resize emit operations;
- auto-layout controls emit operations and recompute geometry;
- export profiles select the correct adapter behavior;
- SVG/PNG/PDF diagnostics are surfaced to the user;
- slots and BrandKit metadata remain canonical scene data.

## Acceptance Checklist

Phase F should not be called done until:

- editor canvas and SVG export agree on page dimensions for custom-size pages;
- custom page/artboard dimensions are editable in the product UI and preserved
  through preflight/export;
- preset choices are only shortcuts that prefill canonical width, height, and
  unit fields; they are not renderer, editor, or export constraints;
- editor canvas and export use computed geometry for layouted nodes;
- common node selection, move, resize, reorder, and undo flows work;
- auto-layout state is inspectable and adjustable;
- slots are visible and previewable in the editor;
- BrandKit/style state is visible and editable through token-safe controls;
- export profiles for SVG, PNG, PDF, print, and preview exist;
- export readiness diagnostics are visible in the product UI;
- visual/export conformance tests cover key branded/slotted/custom-size
  fixtures;
- print limitations are explicit diagnostics rather than hidden mismatches;
- the editor still consumes canonical scene/operations and does not fork design
  semantics into React/Konva state.

## Immediate Next Step

Start with Milestone F-B. It is the highest leverage path because it proves the
user can trust what the editor shows. Without parity, direct manipulation and
export workflows are only cosmetic.

## Editor Contract Lessons From Brilliant And Figma

Phase F should use Brilliant and Figma as architectural reference points, not as
features to copy blindly.

### Brilliant-Derived Rules

Brilliant's strongest editor/runtime idea is that the same authoring object
model drives agent-authored elements, interactive layout, canvas preview, and
export. Its Blueprint language is closer to its disk/wire authoring model than
Lumen's DSL is, but the important product rule still applies to Lumen:

- there must be one canonical object model;
- the editor must operate through the same mutation surface as agents and API;
- layout must be interactive, not only batch-computed for export;
- preview feedback must use the same render/export path users approve.

For Lumen, the canonical object model is `Scene`, not DSL. The Lumen DSL is an
authoring/import surface that compiles into `Operation`s. A user dragging a node
in the editor and an agent editing DSL should converge through the same checked
operation/preflight/export path.

The Brilliant reverse-engineering report also highlights a major Phase F design
requirement: auto-layout cannot be only declarative. Brilliant supports
drag-insertion math, reorder, undo registration, transformed-child handling,
fill-to-hug fallback, and parent resize-to-fit. Lumen already has batch layout
and computed geometry; Phase F must make those computed results usable and
editable in a live editor.

### Figma-Derived Rules

Figma is the reference for a production editor object model. Its API exposes a
document tree of scene nodes, stable node IDs, page/frame/container nodes,
children, absolute bounds, transforms, auto-layout fields, and export operations.
The exact API is not our contract, but the shape validates the architecture:

- editing is node-based, not canvas-bitmap-based;
- frames/pages are exportable surfaces;
- absolute/computed geometry exists for rendering and hit testing;
- auto-layout is encoded as node properties, not hidden renderer behavior;
- export is a method over the same node tree, not a separate authored file.

Relevant Figma references:

- Figma Plugin API node model:
  `https://www.figma.com/plugin-docs/api/nodes/`
- Figma Plugin API typing source:
  `https://github.com/figma/plugin-typings/blob/master/plugin-api.d.ts`
- Figma REST/API file and node model:
  `https://www.figma.com/developers/api`

Lumen's equivalent rule:

```text
Scene JSON + computed geometry
  -> editor render descriptors
  -> Konva nodes for interaction

Scene JSON + computed geometry
  -> ExportRequest
  -> SVG / PNG / PDF / future HTML-CSS adapters
```

Konva nodes are views. They are never source of truth. Export artifacts are
outputs. They are never source of truth. DSL is an authoring language. It is
never source of truth after compilation. If an editor action changes design
state, it must produce an `Operation`; if that operation is accepted, the editor
re-renders from the resulting `Scene`.

### Source-Of-Truth Contract

All renderers and exporters must follow this data flow:

```text
Operation batch
  -> checked apply
  -> Scene
  -> preflight
      -> BrandKit/token resolution
      -> layout/text measurement
      -> computed geometry
      -> diagnostics
  -> render/export adapters
```

The editor may cache render descriptors for performance, but those descriptors
must be invalidated whenever the scene, page, computed geometry, active mode,
or export profile changes.

This applies to all current and future output formats:

- Canvas/Konva preview.
- SVG export.
- PNG export.
- PDF export.
- Print PDF profile.
- Future HTML/CSS export.
- Future Figma export.

The same page size, node hierarchy, computed bounds, text fields, slot metadata,
BrandKit resolution, and export profile must be visible to every adapter.

### Editor-Specific Layout Contract

Batch layout is not enough for a useful editor. Phase F should introduce a
separate editor interaction contract around the existing layout engine:

```text
Scene + active selection + pointer event
  -> editor interaction intent
  -> operation preview
  -> optional layout preview
  -> checked operation commit
  -> preflight/layout recompute
  -> canvas re-render
```

This contract should support:

- free-position drag for absolute/fixed nodes;
- layout-managed drag for children of auto-layout containers;
- insertion-index preview for auto-layout containers;
- reorder preview before commit;
- resize preview for fixed nodes and frame containers;
- disabled or constrained handles for layout-managed children;
- undo/redo via operation history, not Konva snapshots.

If this contract requires layout helper functions that are not currently in
`lumen-core`, they should be added as core/editor-boundary helpers rather than
implemented ad hoc in React.

## Detailed Milestone Implementation Plan

### F0 Detailed Plan: Scope Lock And Parity Contract

Objective:

Build the small contract layer that prevents the editor from drifting away from
export.

Implementation steps:

1. Inventory all scene fields used by `lumen-export` SVG/PNG/PDF paths:
   page size, unit, background, children order, transforms, computed bounds,
   fills, strokes, corner radii, opacity, text fields, image refs, vectors,
   slots, BrandKit refs, export profiles.
2. Inventory the current editor `RenderNodeDescriptor` and mark every missing
   field as supported, placeholder, or deliberately unsupported.
3. Create a renderer parity matrix in docs or tests:
   `Scene field -> Konva preview -> SVG -> PNG -> PDF`.
4. Define the allowed editor fallback rules:
   unresolved image asset placeholder, unsupported vector placeholder,
   unsupported text shaping warning, unsupported effect hidden with diagnostic.
5. Create an `EditorRenderUnsupportedDiagnostic` convention so the UI can show
   "this node exports but preview is approximate" instead of silently lying.
6. Add unit tests around descriptor generation for custom pages, computed
   geometry, non-visual groups, text, image placeholders, and slot metadata.

Deliverables:

- Updated render descriptor contract.
- Parity matrix.
- Descriptor tests.
- Unsupported-preview diagnostic conventions.

Risks:

- Too much parity testing at once can slow implementation. Start with geometry,
  then text, then assets/effects.

### F1 Detailed Plan: Canvas Rendering Parity

Objective:

Make the canvas a faithful interactive preview of the preflighted scene.

Implementation steps:

1. Ensure the editor loads/renders the preflighted scene when available, not the
   raw pre-layout scene, for approval/export workflows.
2. Normalize page dimensions through the same unit conversion used by export.
3. Render pages as exportable artboards with exact bounds, background, bleed,
   and safe-area overlays.
4. Render nodes in scene child order:
   page children first, then recursive container children.
5. Use `computed.layout_bounds` for visual geometry when present.
6. Use `computed.render_bounds` for selection bounds where it differs from
   layout bounds.
7. Render non-visual groups as transparent interaction containers only when
   selected/hovered.
8. Render text using the current text fields:
   content, family, size, weight, alignment, line-height, letter spacing, wrap,
   max lines, and direction.
9. For text fields Konva cannot match exactly, expose approximation diagnostics
   and keep SVG export as fidelity baseline.
10. Render images/logos with fixture/object URL support when available and
    placeholders when bytes are unavailable.
11. Render vectors/SVG path data where supported by Konva or through an SVG
    image fallback; otherwise show a placeholder and export warning.
12. Add a page zoom/pan layer that does not affect scene coordinates.

Deliverables:

- Accurate page/artboard renderer.
- Geometry-first node renderer.
- Text renderer parity pass.
- Placeholder strategy for unresolved assets/vectors.
- Tests proving 1080x1080 page parity and computed-geometry parity.

Exit criteria:

- The square-ad failure is impossible at the editor surface because the canvas
  and export both honor custom page dimensions.

### F2 Detailed Plan: Selection, Handles, Drag, Resize, And Undo

Objective:

Let users correct common design problems directly.

Implementation steps:

1. Tag every Konva visual with canonical `nodeId`, `pageId`, and optional slot
   keys.
2. Implement hit testing that ignores editor overlays unless explicitly
   selected.
3. Implement a selection model:
   selected page, selected node, multi-select later, hover node, focused
   inspector field.
4. Use Konva `Transformer` or custom handles for fixed nodes.
5. Convert canvas-space deltas back into scene units before creating
   operations.
6. Emit canonical `UpdateNode`/move/size operations for free-positioned nodes.
7. Disable or constrain movement for layout-managed children, with a visible
   explanation and a path to "reorder in layout" instead.
8. Add undo/redo from accepted operations or snapshot stack. Do not rely on
   Konva object mutation as history.
9. Show page bounds, snapping guides, center lines, and safe-area guides.
10. Add keyboard shortcuts for delete, undo, redo, arrow nudging, escape, and
    page focus.

Deliverables:

- Selection/hit-test tests.
- Drag operation tests.
- Resize operation tests.
- Undo/redo tests.
- Page-switch selection safety tests.

Dependency note:

If move/resize operations are too coarse for all node kinds, add the missing
operation patches to core before building UI-specific workarounds.

### F3 Detailed Plan: Auto-Layout Controls And Live Layout Feedback

Objective:

Expose the layout engine as a product feature.

Implementation steps:

1. Identify current `AutoLayoutProps` fields and which are mutable by existing
   operations.
2. Add inspector controls for direction, wrap, gap, padding, x/y alignment,
   child fill/hug/fixed sizing, and transformed-child state.
3. Add a layer/tree panel for child order within page/group/auto-layout
   containers.
4. Implement reorder buttons first. Add drag-to-reorder after operation and
   preview semantics are stable.
5. Add layout previews:
   candidate insertion index, before/after gap, and container bounds.
6. Add a core helper if needed:
   `compute_insertion_index(container_id, pointer, scene)`.
7. Add a core helper if needed:
   `preview_layout_after_operation(scene, operation)`.
8. On commit, apply operation through checked core/editor engine and rerun
   preflight/layout.
9. Show layout diagnostics at the container and affected children.
10. Prevent free-position drag from corrupting layout-managed children.

Deliverables:

- Auto-layout inspector.
- Child order/layer controls.
- Reorder operation flow.
- Insertion preview helper, if needed.
- Tests for gap/padding/alignment/reorder.

Dependency note:

Brilliant's editor has drag-insertion and reorder-undo integrated into the
layout engine. If Lumen's current layout engine does not expose insertion-index
math, that should become a core layout/editor contract dependency, not a React
implementation detail.

### F4 Detailed Plan: Slot Inspector And Content Preview

Objective:

Make semantic template state visible to the user.

Implementation steps:

1. Build a page-aware slot summary:
   slot key, slot id, content type, required state, bound nodes, scope, sample
   content, overflow policy, fit diagnostics.
2. Show slot badges on selected nodes and optional canvas overlays.
3. Add slot inspector controls for supported slot metadata only.
4. Add content preview for sample/worst-case fixtures.
5. Show required/missing/overflow diagnostics inline.
6. Add operations for supported binding/unbinding/editing. If operations are
   missing, record them as dependencies rather than mutating scene JSON.
7. Keep conditionals/repeaters read-only unless Phase G/runtime semantics are
   implemented.

Deliverables:

- Slot summary UI.
- Slot-to-node binding visibility.
- Slot fit diagnostics in editor.
- Tests for slot inspector state and operations.

Dependency note:

Full conditional/repeater runtime belongs to Phase G or a dedicated slot-runtime
branch. Phase F should only display scaffolds and validate obvious states.

### F5 Detailed Plan: Brand And Style Inspector

Objective:

Let users keep generated designs on brand while making visual corrections.

Implementation steps:

1. Display effective BrandKit id/version/mode and approval state.
2. Load token catalog summaries from the available BrandKit list or API shell.
3. Add field-specific token pickers:
   fills, strokes, text style, radius, opacity, layout gap, layout padding.
4. Clearly label raw values versus token-backed values.
5. Run brand governance through the existing runner.
6. Run compatibility checks through the existing runner.
7. For unresolved/missing BrandKit context, show action-oriented diagnostics.
8. Add style previews in the inspector: color swatches, type samples, radius
   examples.
9. Emit canonical operations for token changes.
10. Do not store copied token maps in scene JSON.

Deliverables:

- Brand/style inspector improvements.
- Token-safe operations.
- Governance/compatibility diagnostics.
- Tests for token picker operation emission.

Dependency note:

Approval workflows and website/style-guide extraction are not Phase F. They
remain BrandKit/product-management work.

### F6 Detailed Plan: Export Product Surface

Objective:

Give users a real export workflow, not a developer test adapter.

Implementation steps:

1. Define product export profiles:
   SVG preview, SVG download, PNG preview, PNG download, PDF draft, PDF print,
   future HTML/CSS.
2. Add an export panel with:
   active page/all pages, format, scale/DPI, print intent, bleed inclusion,
   sidecar metadata toggle.
3. Route export through API/helper/core rather than client-side reimplementation
   where possible.
4. Show export readiness diagnostics before download.
5. Store export profile choices in document metadata when the operation surface
   supports it.
6. Generate export artifacts and show artifact summaries:
   filename, format, pages, warnings, file size, dimensions.
7. Add "copy SVG" and "download" commands where safe.
8. Treat HTML/CSS as a future adapter consuming the same `ExportRequest` and
   scene geometry. Do not make HTML/CSS a new authoring source of truth.
9. Add bulk preview export for all pages without personalized binding sets.

Deliverables:

- Export panel.
- Export profile DTOs.
- Artifact summary UI.
- API/helper wiring.
- SVG/PNG/PDF product tests.

Dependency note:

Bulk personalized exports belong to Phase G. Phase F can export all current
pages/artboards, but not generate account/contact variants.

### F7 Detailed Plan: Preview And Export Parity Mode

Objective:

Let users and agents compare interactive canvas preview with export output.

Implementation steps:

1. Add view modes:
   canvas, export preview, split compare.
2. Generate an SVG or PNG artifact for the active page.
3. Display the generated artifact inside the editor.
4. Show parity status:
   page size match, node count match, text presence, unresolved tokens, export
   diagnostics.
5. Attach export preview artifact paths to agent/critic runs when invoked from
   the product shell.
6. If debug preview is generated despite preflight warnings, mark it invalid
   and prevent acceptance until errors are resolved.
7. Add parity tests for branded square fixture and multi-page fixture.

Deliverables:

- Export preview mode.
- Split/toggle compare.
- Parity diagnostics.
- Agent-compatible preview artifact contract.

Dependency note:

The critic loop from Phase A should consume export preview artifacts, not a
separate canvas screenshot, when fidelity matters.

### F8 Detailed Plan: Visual Regression And Export Conformance

Objective:

Make parity measurable and protect it in CI.

Implementation steps:

1. Create a fixture manifest for:
   square ad, email hero, one-pager, report cover, slotted page, multi-page
   document, layout-managed page, BrandKit-tokenized page.
2. For each fixture, run:
   DSL compile if applicable, operation apply, preflight, export, editor
   descriptor generation.
3. Assert page dimensions and computed node bounds are identical between editor
   descriptors and export sidecars.
4. Assert SVG contains expected metadata:
   document id, page id, node ids, slot keys, resolved fills, text.
5. Add PNG smoke tests for nonblank artifacts.
6. Add PDF structural tests for page count, dimensions, diagnostics.
7. Add ignored visual snapshots for unstable pixel tests until the renderer is
   stable enough for CI.
8. Add a "known divergence" list so approximate fields are explicit.

Deliverables:

- Shared fixture manifest.
- Editor/export parity tests.
- SVG/PNG/PDF conformance tests.
- Known divergence register.

Dependency note:

Pixel-perfect tests require stable fonts/assets. Until Phase E and print
fidelity are stronger, prefer geometry/metadata/content assertions plus limited
smoke image checks.

### F9 Detailed Plan: Print Fidelity Guardrails

Objective:

Make print export honest and progressively useful.

Implementation steps:

1. Display safe-area and bleed overlays in the editor.
2. Add print profile fields:
   PDF intent, include bleed, DPI, crop/safe-area checks, font embedding
   requested.
3. Add export diagnostics for:
   missing bleed, unsafe required slots, text overflow, unresolved tokens,
   missing font embedding support, missing image DPI, unsupported RTL/non-Latin
   shaping.
4. Ensure PDF dimensions match page size plus optional bleed.
5. Add explicit warnings when using fallback fonts.
6. Keep PDF export from claiming final print readiness until font and asset
   runtime dependencies are satisfied.
7. Add tests for safe-area/bleed metadata and PDF dimension behavior.

Deliverables:

- Safe-area/bleed overlays.
- Print profile controls.
- Print diagnostics.
- PDF quality guardrail tests.

Dependency note:

Final font embedding/subsetting, robust text shaping, and print-house-specific
PDF compliance belong to later print-fidelity work. Phase F should define the
product surface and diagnostics now.

## Dependency Ledger For Later Phases

The following dependencies should be recorded explicitly. They are needed for a
full production editor, but they should only be implemented in Phase F if they
are required to satisfy the editor/export usability goal now.

### Phase D Dependencies

- DSL `#node` modify lowering for agent-side targeted edits.
- DSL `before`, `after`, `replace`, `clone`, checkpoint, undo, and redo
  semantics.
- Structured agent edit tool that emits operation patches without regenerating
  pages.
- Repair policy that chooses between DSL, operations, asset tools, and planner.
- Text replacement/editing protocol for agent repairs.

Why deferred:

Human editor operations can use structured operations directly in Phase F.
Agents need Phase D for reliable targeted repair, but the editor does not need
to wait for the DSL modify language.

### Layout/Core Dependencies

- Core/editor helper for auto-layout insertion-index computation.
- Core/editor helper for layout preview after a proposed reorder or drag.
- Core operation support for all layout edits exposed by the UI.
- Better distinction between absolute children and flow-managed children.
- Applied shrink-font or fit-policy operations if the editor exposes automatic
  fit fixes.
- Stable operation semantics for drag-reparenting across layout containers.

Why conditional:

If Phase F only exposes simple reorder buttons and direct fixed-node movement,
these can wait. If Phase F implements Brilliant/Figma-grade drag insertion,
these must become core contracts first.

### Phase E Dependencies

- Real asset byte resolver for editor preview.
- Upload/import API and asset library.
- SVG sanitization and MIME probing.
- Image dimensions, DPI, thumbnails, focal point, crop, and fit policies.
- Image generation/vectorization providers.
- Font file storage, probing, and availability checks.

Why deferred:

Phase F can render placeholders and fixture assets, but production imagery and
font runtime belong to Phase E. Export should diagnose missing bytes rather than
guess.

### Print Fidelity Dependencies

- Font embedding/subsetting.
- Non-Latin/RTL shaping and bidi behavior.
- Hyphenation and real font metrics.
- PDF/A or print-house quality profiles.
- Automatic pagination of flowed documents.

Why deferred:

Phase F should create print profiles, safe-area/bleed UI, and warnings. Final
print fidelity requires dedicated engine/export work.

### Future Figma/HTML-CSS Export Dependencies

- Figma import/export mapping from Lumen scene nodes to Figma node types.
- HTML/CSS export adapter that consumes `Scene` and computed geometry.
- CSS layout strategy for absolute-positioned artboards versus semantic HTML.
- Round-trip limitations and metadata preservation rules.

Why deferred:

Figma and HTML/CSS must be adapters over the canonical scene. They should not
introduce a second source of truth or become the editor's internal model.

## Final Product Principle

Phase F succeeds only if the editor is trustworthy.

Trustworthy means:

- a user sees the same dimensions the exporter will produce;
- a user edits the same scene the agent and API use;
- the canvas is a projection of computed scene geometry, not a separate canvas
  document;
- every visible edit can be replayed through operations;
- every export format consumes the same scene/preflight result;
- every approximation is called out as a diagnostic, not hidden.

This is the line that keeps Lumen closer to Figma and Brilliant's strongest
architectural lessons while still preserving Lumen's platform-specific choice:
`Scene` and `Operation` are canonical, and DSL is one authoring path into them.
