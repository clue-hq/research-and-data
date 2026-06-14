# Artboard Workspace And Canonical Geometry Plan

Date: 2026-06-14
Branch: `editor/artboard-workspace-spec-v0`
Base: `editor/canvaskit-canvas-v0` at `8cc5c7d`
Status: planning/specification only

## Purpose

Lumen should adopt the part of the Brilliant/Figma model that solves real
product failures without trying to become a general-purpose Figma replacement:
the editor workspace can be infinite, but exportable artifacts are bounded
artboards/frames. The workspace is where a user pans, zooms, inspects multiple
artifacts, and eventually keeps scratch objects. The artboard is the thing that
has design geometry, validation, slots, Brand Kit constraints, and export
profiles.

This plan defines the work slices needed to get there:

1. Canonical Artboard Geometry.
2. Editor Chrome / Product Shell.
3. Infinite Canvas Workspace V0.
4. Artboard-As-Frame Generation.
5. CanvasKit / Editor Interaction Polish.
6. Loose Workspace Objects Later.

The ordering is deliberate. The current run-trace failures are not caused by
CanvasKit or Konva. They are caused by an inconsistent geometry contract: the
page exports as an A4 `210mm x 297mm` surface while generated children use
`595 x 842` point-like coordinates. The editor should expose a better mental
model, but the compiler/preflight/export path must enforce it.

## Source-Of-Truth Alignment

This spec follows the existing ABM Design Engine architecture:

- One deterministic design engine is used by agents, editor, export, and future
  automation.
- A page/artboard is an exportable design surface.
- Renderer technology does not own design semantics.
- The editor is a projection of canonical `Scene` plus computed geometry and
  emits canonical `Operation`s.
- Presets are convenience shortcuts; valid explicit artifact dimensions are
  first-class.

It also follows the Brilliant-derived principles documented in the reference
analysis:

- Element geometry is parent-local except for objects attached to the workspace
  root.
- Design surfaces are frames/parents, not renderer canvases.
- Backgrounds should normally be fills on the parent frame, not separate
  oversized rectangles.
- Auto-layout, fill, hug, fixed sizing, wrapping, padding, and gaps are the
  default way to keep children inside frames.
- The compiler/runtime should lint and repair design-intent failures such as
  impossible layout, out-of-bounds content, ghost frames, and clipping.
- Export operates on selected bounded surfaces and scales those surfaces to the
  requested PNG/PDF/SVG output.

## Observed Failure To Resolve

The CanvasKit worktree contains persisted `.lumen-runs` that prove the problem.
Representative examples:

- `run_e1c0a72f4ebf4533af862cac725b7783` authored
  `page page_a4 preset(a4,portrait)` and then placed `bg s(595,842)` plus
  `card p(97,221) s(400,400)`. The exported SVG is `width="210mm"`
  `height="297mm"` with `viewBox="0 0 210 297"`, so the background and card are
  far larger than the page coordinate space.
- In the same run, later surgical repairs only adjusted text and card height.
  They did not fix the page/artboard coordinate mismatch because preflight did
  not emit a generic page-bounds diagnostic for `bg` or `card`.
- `run_d25cf14147754f4ab188165f355b12ec` shows why a simple one-node fix is not
  enough. A later repair changed `bg` to `210 x 297` and `card` to
  `170 x 210`, but child nodes such as `header` and `divider` kept their
  original `400`/`352` widths inside a `170`-wide card.
- Both runs still reached `max_iterations_reached` even after destructive repair
  was fixed. The loop had real previews and non-destructive modify lines, but
  it lacked the geometry diagnostics and layout-cluster repair authority needed
  to solve the actual issue.

The fix must therefore cover all of these failure classes:

| Failure | Required fix |
|---|---|
| A4 page uses `210 x 297` while children use `595 x 842` | Normalize presets/custom sizes into canonical layout points before children are interpreted. |
| Background is a separate oversized rect | Make the artboard/root frame carry the background fill. |
| Parent is resized but children remain too large | Add parent-containment diagnostics and layout-cluster repair. |
| Preflight reports only text/slot overflow | Add generic page/artboard bounds and parent bounds diagnostics. |
| CanvasKit draws off-page nodes over the editor backdrop | Clip artboard content in the renderer, but keep diagnostics so clipping is not mistaken for correctness. |

## Canonical Unit Decision

Use `pt` as the canonical scene/layout unit.

`pt` here means a deterministic scene point:

- For print surfaces, it maps to physical points: `1in = 72pt`.
- For metric print sizes, convert through inches:
  `pt = mm / 25.4 * 72`.
- For raster/social surfaces, the authored pixel size maps numerically to layout
  points at the default raster scale. A `1080 x 1080 px` LinkedIn artboard has a
  `1080 x 1080 pt` layout coordinate space and a default raster export of
  `1080 x 1080 px`.
- Renderers may scale layout points to device pixels for preview, zoom, or
  export, but node `p()` and `s()` values are never renderer pixels and never
  millimeters.

Examples:

```text
A4 portrait preset
  layout: 595.276 x 841.890 pt
  display label: A4 portrait, 210mm x 297mm
  print metadata: 210mm x 297mm
  default SVG/PDF physical size: 210mm x 297mm

US Letter
  layout: 612 x 792 pt
  print metadata: 8.5in x 11in

LinkedIn square
  layout: 1080 x 1080 pt
  raster default: 1080 x 1080 px

Custom 6in x 4in print
  layout: 432 x 288 pt
  print metadata: 6in x 4in
```

The agent should author against layout dimensions only. Physical print metadata
and raster output dimensions belong to `PageGeometry`/export profiles and should
not leak into child node coordinates.

## Target Mental Model

```text
Document
  Workspace / infinite canvas
    Artboard A: LinkedIn ad
      workspace origin: (0, 0)
      layout bounds: 1080 x 1080 pt
      raster default: 1080 x 1080 px
      children: artboard-local coordinates

    Artboard B: A4 letter
      workspace origin: (1280, 0)
      layout bounds: 595.276 x 841.890 pt
      print metadata: 210mm x 297mm
      children: artboard-local coordinates

    Loose draft objects
      workspace-local coordinates
      not export-safe until inserted into an artboard
```

## Screenshot-Derived Editor UI Target

The screenshot target should be treated as a product direction for the editor,
not as decoration. It has three separable pieces:

1. **Editor chrome / product shell**: dark left layers panel, dark right
   inspector/agent/export panel, compact top area, top artboard label, mode
   switch, and a floating bottom toolbar.
2. **Infinite canvas workspace**: light central workspace, panning and zooming,
   one or more bounded artboards, artboard labels, clipping, fit-to-frame, and
   visible export target.
3. **Figma/Brilliant-style interaction polish**: precise selection chrome,
   tool modes, handles, layer selection, inspector state, agent/editor modes,
   diagnostics badges, and export readiness affordances.

The intended first product experience is:

```text
dark left panel        light infinite workspace             dark right panel
pages/layers           bounded artboard(s), labels          inspector/agent/export
                       floating bottom toolbar
                       compact mode switch / top label
```

This UI target should land after canonical geometry, not before it. A polished
shell around incorrect artboard dimensions would make broken exports look more
trustworthy. The shell should expose the correct mental model: the central
workspace is navigational; the bounded artboard is the artifact; diagnostics
explain when an artifact is not export-safe.

### Visual Principles

- Use restrained, operational editor chrome, not a marketing-style page.
- Keep the central canvas light and quiet so artboards and diagnostics carry the
  attention.
- Use dark neutral side panels for persistent product chrome: layers/pages on
  the left, inspector/agent/export/diagnostics on the right.
- Keep artboards as real bounded surfaces with labels, subtle outlines, and
  export-state badges. Do not wrap artboards in decorative cards.
- Use a compact floating bottom toolbar for tools such as select, hand/pan,
  frame/artboard focus, zoom, fit, comments/diagnostics, and export preview.
- Prefer icon-first controls with tooltips for tools. Text labels should appear
  where they clarify state, such as active mode, active artboard, selected layer,
  or export profile.
- Avoid nested cards inside panels. Use panel sections, rows, tabs, split
  controls, and compact lists.
- Side panels must be collapsible on smaller screens; the artboard remains the
  primary surface.
- Diagnostics should be visible without hiding the artifact. Use badges,
  focused outlines, panel rows, and click-to-focus behavior rather than large
  blocking overlays.
- The editor should support keyboard-driven inspection: escape/deselect,
  delete/duplicate where supported, zoom/fit shortcuts, layer navigation, and
  focus states.

### Product Shell Scope

The product shell is a UI commitment, not a new scene model:

- left panel: pages/artboards, layers, nested hierarchy, selected-node state;
- right panel: inspector, agent, export, diagnostics, slots/brand panels as
  tabs or compact mode sections;
- top artboard label: current artboard name, size, export-safe state, active
  mode;
- compact mode switch: edit, agent, preview/export, diagnostics;
- floating bottom toolbar: select, pan, zoom, fit current, fit all, artboard
  focus, diagnostics toggle, export preview;
- central status affordances: clipped content badge, preflight warning count,
  export profile state.

The shell must remain a projection of scene/preflight/export state. It must not
own hidden design semantics, hidden export settings, or renderer-only geometry.

## Core Contract

### PageGeometry

Add a normalized geometry object before nodes are interpreted:

```text
PageGeometry {
  layout_width_pt: f32,
  layout_height_pt: f32,
  layout_unit: "pt",

  source_kind: Preset | ExplicitSize,
  source_width: Option<f32>,
  source_height: Option<f32>,
  source_unit: Option<Px | Pt | In | Mm>,

  intent: Raster | Print | Vector | Mixed,

  physical_width: Option<f32>,
  physical_height: Option<f32>,
  physical_unit: Option<In | Mm>,

  raster_width_px: Option<u32>,
  raster_height_px: Option<u32>,
  raster_scale: Option<f32>,

  bleed_pt: Option<EdgeInsets>,
  safe_area_pt: Option<EdgeInsets>
}
```

The exact Rust naming can follow existing `PageSize`/`ExportProfile` style, but
the contract must preserve these separations:

- layout dimensions;
- source declaration;
- physical print metadata;
- raster defaults;
- bleed/safe-area values converted to layout points.

### Artboard Placement

An artboard has two coordinate contexts:

- `workspace_origin_pt`: where the artboard appears in the infinite editor
  workspace;
- `layout_bounds_pt`: the local coordinate space children use and export
  consumes.

V0 may synthesize workspace origins in the editor from page order to avoid a
large persistence change. Persistent workspace placement can be added once the
editor needs user-controlled multi-artboard positioning.

### Artboard Children

Children of an artboard are artboard-local. A node at `p(24,24)` on an A4
artboard means `24pt` from the artboard's top-left corner, not from the infinite
workspace and not `24mm`.

### Export

Export chooses one or more bounded artboards:

```text
artboard layout geometry
  -> SVG viewBox in pt
  -> SVG physical width/height for print if present
  -> PNG raster scale/profile dimensions
  -> PDF page/media/trim/bleed boxes
```

No export adapter should infer dimensions from inner nodes. Inner frames can be
visual objects, but they are not a workaround for missing page/artboard size.

## Slice 1: Canonical Artboard Geometry

### Purpose

Fix the engine contract that caused the run-trace failures. Every preset and
custom size must lower into one layout coordinate system before child geometry
is interpreted, laid out, rendered, validated, or exported.

### Scope

Build:

- Normalize `PageSize`/page preset/custom size into canonical `PageGeometry`.
- Make layout dimensions always `pt`.
- Store print physical dimensions separately from layout dimensions.
- Store raster defaults separately from layout dimensions.
- Convert safe area and bleed into points.
- Make SVG/PNG/PDF/export sidecars consume normalized geometry.
- Add generic page/artboard-bounds and parent-containment diagnostics.
- Update DSL/custom-size parsing so explicit sizes are source-of-truth.
- Update tests and fixtures for A4, Letter, square social, landscape social,
  portrait social, email header, and custom print.

Do not build:

- Infinite workspace UI.
- Loose workspace objects.
- Full Figma-style frame drag/reparenting.
- New visual design controls beyond what is needed to expose the corrected
  geometry.

### Engine Requirements

1. `preset(a4,portrait)` must produce `layout_width_pt ~= 595.276` and
   `layout_height_pt ~= 841.890`, not `210 x 297` layout coordinates.
2. `page square size(1080,1080,px)` must produce `1080 x 1080 pt` layout
   coordinates and `1080 x 1080 px` default raster metadata.
3. `page custom size(210mm,297mm)` must produce A4-equivalent layout points and
   physical metadata of `210mm x 297mm`.
4. `page custom size(6in,4in)` must produce `432 x 288 pt` layout coordinates
   and physical metadata of `6in x 4in`.
5. Invalid dimensions must diagnose before export:
   zero, negative, non-finite, unsupported units, and unsafe raster sizes.
6. Presets are shortcuts. Renderer/export capability checks must be based on
   normalized valid geometry, not preset names.

### Diagnostics

Add diagnostics for:

- Top-level node exceeds artboard bounds.
- Top-level node starts outside artboard bounds.
- Child render bounds exceed parent bounds when the parent is a bounded frame,
  auto-layout frame, clipped container, or root artboard.
- A background-like top-level frame/rect exactly or mostly covers the artboard
  and should become artboard background fill.
- Child geometry appears to use a different unit scale than the parent, e.g.
  `400pt` child inside `170pt` parent after a parent resize.

Diagnostics should name the target node and the containing artboard/parent:

```text
LUMV09xx node card exceeds artboard page_a4:
  bounds right=497pt bottom=471pt outside 595.276 x 841.890pt
  hint: resize/reposition card or move it into an auto-layout artboard frame.

LUMV09xy node header exceeds parent card:
  child width=400pt parent width=170pt
  hint: use s(fill, fixed) or resize the layout cluster.
```

The exact diagnostic codes should follow the existing code taxonomy, but the
messages must make unit and containment failures explicit enough for both human
editor surfaces and agent repair.

### Run-Trace Resolution

This slice resolves:

- `bg s(595,842)` on A4 no longer overflows because A4 layout is itself
  `595.276 x 841.890 pt`.
- `card p(97,221) s(400,400)` becomes a valid A4 point-space card instead of a
  `400mm`-wide card on a `210mm` page.
- If a design still creates a child larger than its parent, preflight emits a
  direct parent-containment diagnostic instead of only text overflow warnings.

### Acceptance

- A4 appointment-card reproduction compiles to an A4 artboard whose SVG viewBox
  is in points and whose physical SVG dimensions remain `210mm x 297mm`.
- The same scene no longer overflows solely because of A4 mm/pt mismatch.
- A synthetic scene with a `400pt` child inside a `170pt` frame emits a
  parent-containment diagnostic.
- Export sidecars report both layout size and physical/raster metadata.
- Editor descriptors, SVG, PNG, PDF, and preflight agree on page/artboard
  layout dimensions.

### Verification

- Rust unit tests for unit conversion and preset normalization.
- DSL compiler tests for explicit sizes in `px`, `pt`, `in`, and `mm`.
- Preflight tests for artboard bounds and parent bounds.
- Export tests for SVG viewBox, SVG physical attributes, PNG dimensions, and PDF
  media size.
- Editor descriptor tests proving CanvasKit/Konva descriptors consume the same
  normalized geometry.

## Slice 2: Editor Chrome / Product Shell

### Purpose

Establish the screenshot-inspired editor product shell: dark side panels,
compact controls, floating toolbar, and clear mode/selection/export state. This
is the product frame that lets users inspect, correct, approve, and export
artifacts without hiding the canonical scene contract.

### Scope

Build:

- Dark left product panel for pages/artboards and layers.
- Dark right product panel for inspector, agent, export, diagnostics, slots, and
  brand surfaces.
- Compact top artboard label with current artboard name, dimensions, mode, and
  export-safe state.
- Compact mode switch for edit, agent, preview/export, and diagnostics.
- Floating bottom toolbar for selection, pan/hand, zoom, fit-current,
  fit-all-artboards, artboard focus, diagnostics, and export preview.
- Collapsible panel behavior for constrained screens.
- Shared shell state model that reads canonical scene, selected node, active
  artboard, diagnostics, and export profile state.

Do not build:

- New scene or workspace persistence semantics.
- Loose scratch objects.
- Full Figma-style tool system.
- A separate local editor document model.
- Decorative redesign that changes no product workflow.

### Shell Requirements

1. The shell must keep the central artboard/workspace as the primary surface.
2. The left panel reads canonical page/artboard and node hierarchy order.
3. The right panel reads and writes through canonical operations or existing
   preflight/export APIs.
4. Mode switches change product mode only; they do not fork scene semantics.
5. The bottom toolbar controls viewport/tool state, not document geometry.
6. Diagnostics and export status are visible in both the artboard label and the
   right panel.
7. The shell must work with CanvasKit and Konva during the flag period.
8. The shell should not make unvalidated or clipped scenes appear final.

### Implementation Placement

This slice can ship in `editor/infinite-workspace-v0` together with Slice 3, but
it should remain separately testable. If the UI shell is implemented before the
workspace, it must still be wired to the existing active page and existing canvas
without changing scene geometry.

### Acceptance

- The editor has the intended dark-left / light-center / dark-right product
  structure.
- The active artboard label shows dimensions and validation/export state.
- The right panel can switch between inspector, agent, export, and diagnostics
  without remounting or mutating the scene.
- The bottom toolbar controls viewport/tool state and remains independent of
  export geometry.
- Collapsing side panels does not hide critical diagnostics or prevent export.

### Verification

- Component tests for shell mode switching, tab persistence, and active-artboard
  label state.
- Accessibility checks for focus order, panel collapse controls, mode switch,
  and toolbar tooltips.
- Playwright screenshots for desktop and smaller viewport layouts.
- Regression tests proving shell mode switches do not emit scene operations.

## Slice 3: Infinite Canvas Workspace V0

### Purpose

Expose the correct canvas mental model to users: the editor workspace is larger
than any one artifact, while each page/artboard is a bounded export surface.
This is workspace and renderer composition. It does not replace the geometry
contract from Slice 1, and it relies on the shell affordances from Slice 2 to be
usable.

### Scope

Build:

- A pan/zoom workspace with an unbounded background.
- One or more artboards rendered as positioned bounded frames.
- Artboard labels and selection state.
- Artboard clipping in CanvasKit/Konva so off-artboard content does not paint
  over the workspace backdrop.
- Fit-to-artboard, fit-all-artboards, and zoom controls.
- Page/artboard rail selection mapped to workspace focus.
- Export-selected-artboard behavior in the editor export panel.
- Diagnostics badges on artboards with overflow/export issues.
- Light central workspace styling that visually separates the workspace from the
  dark product chrome.

Do not build:

- Persistent arbitrary user placement of artboards unless it falls out cheaply.
- Loose scratch objects.
- Full freeform Figma editing behavior.
- Multi-user collaboration.
- Plugin/import/export to Figma.

### Editor Requirements

1. The workspace has its own viewport transform: pan, zoom, and fit.
2. Artboards have workspace positions but children render in artboard-local
   points.
3. The renderer clips artboard content to the artboard bounds by default.
4. Clipping is a display guard only. Preflight diagnostics still report
   clipped/off-artboard content.
5. Selection chrome and handles use artboard-local geometry transformed through
   the workspace viewport.
6. Drag/resize gestures continue to emit canonical operations against nodes,
   not renderer-local state.
7. Artboard selection and export selection share a single active page/artboard
   concept.

### CanvasKit Interaction

CanvasKit should draw scene content only. Selection chrome, artboard labels,
handles, guides, hover outlines, and diagnostics badges should remain in the
DOM/SVG overlay where possible. This preserves the CanvasKit workstream decision
that hover/selection should not trigger wasm redraws.

### Run-Trace Resolution

This slice makes the visual symptom less misleading:

- Off-artboard content cannot cover the editor backdrop.
- The user can see the artboard frame and understand what will export.
- The diagnostics badge can show "content clipped/out of bounds" even when the
  renderer clips the content.

It does not by itself fix the underlying bad scene. Slice 1 and Slice 4 do that.

### Acceptance

- A document with A4 and square social artboards displays both in one workspace.
- Fit-to-current and fit-all-artboards work without changing scene dimensions.
- The active export target is visually clear.
- Off-artboard test content is clipped in the editor and still diagnosed by
  preflight.
- CanvasKit and Konva paths agree on artboard position, zoom, clipping, and
  selection geometry during the flag period.

### Verification

- Component tests for viewport transform and artboard placement.
- Playwright visual checks for desktop and small viewport pan/zoom/fit.
- CanvasKit pixel checks showing nonblank artboards and clipped off-artboard
  content.
- Export-panel tests proving selected artboard scope reaches export requests.
- Gesture conformance tests proving operations are unchanged by workspace
  transform.

## Slice 4: Artboard-As-Frame Generation

### Purpose

Teach the agent and DSL authoring protocol to create export-safe pages the
Brilliant way: the artboard/root frame carries background, layout, clipping, and
padding; children use parent-local fill/hug/fixed coordinates; repair can adjust
layout clusters rather than isolated text boxes.

### Scope

Build:

- Agent knowledge updates for canonical points and artboard-local coordinates.
- DSL examples that use A4 `595 x 842 pt` layout space and digital social
  `1080 x 1080 pt` layout space.
- Root artboard/page background fill guidance.
- Auto-layout-first recipes for cards, headers, CTA rows, appointment/reminder
  layouts, report covers, and social ads.
- A layout-cluster repair route for page/artboard and parent-containment
  diagnostics.
- Repair permissions that allow bounded multi-node fixes for a root cluster
  without allowing destructive whole-scene rewrite.

Do not build:

- A new LLM provider.
- Unbounded full-page regeneration after every diagnostic.
- A general optimizer that redesigns arbitrary layouts.
- Freeform scratch-object authoring.

### Authoring Rules

The preferred generated structure is:

```text
page page_a4 preset(a4,portrait)
  artboard al(v,g(18),pad(36)) s(fill,fill) fill($surface.page) clip
    card al(v,g(12),pad(18)) s(fill,hug) fill($surface.card) rd(12)
      ...
```

If the current DSL cannot make `page` itself a layout parent in the desired way,
the temporary pattern is:

```text
page page_a4 preset(a4,portrait)
  artboard fr p(0,0) s(page.w,page.h) fill($surface.page) clip
    card al(v,g(12),pad(18)) p(48,96) s(499,hug)
      ...
```

Rules:

- Use `pt` layout dimensions.
- Do not use `mm` for child node `p()`/`s()`.
- Do not create a separate `bg` rectangle unless a real layered visual object is
  needed.
- Use artboard/page fill for background.
- Use `fill`, `hug`, fixed values, padding, gap, and wrap before absolute child
  coordinates.
- When a parent changes size, update the affected layout cluster, not just one
  child.

### Repair Policy

Current surgical repair is too narrow for page-scale mistakes. Keep the
non-destructive protection, but add a broader repair class:

```text
repair_class: layout_cluster
targets:
  artboard/page id
  root frame id
  affected parent id
  affected descendant ids
allowed operations:
  modify p/s on target cluster
  modify al/pad/gap/wrap/fill/hug/fixed on target cluster
  convert background rect into artboard fill
disallowed operations:
  delete page
  delete unrelated nodes
  re-author entire scene
  change unrelated slots/brand tokens/assets
```

This directly covers the `run_d25...` case where changing `card` without
changing `header`/`divider` left the layout inconsistent.

### Run-Trace Resolution

This slice resolves:

- Agent stops mixing physical A4 mm dimensions with point-like child sizes.
- Appointment-card style layouts use a root artboard/card layout instead of
  loose fixed nodes.
- Parent resize repairs update descendants that depend on the parent.
- Preflight output can drive a bounded multi-node repair instead of repeatedly
  shrinking only text nodes.

### Acceptance

- The appointment-reminder prompt produces an A4 artifact whose background is an
  artboard fill or correctly sized root frame, not an oversized `bg`.
- The generated card and descendants stay within the artboard and parent card.
- Quality loop repair for a parent-bounds diagnostic emits layout-cluster modify
  operations, not a destructive block and not only text-size tweaks.
- The run reaches either accepted or a failure with explicit remaining product
  gaps unrelated to coordinate mismatch.

### Verification

- Agent-runtime knowledge tests proving required excerpts include canonical
  point guidance and no stale `595 x 842 on 210 x 297` ambiguity.
- Deterministic fixture prompts for A4, Letter, 1080 square, and 1200x628.
- Trace evaluator checks for absence of oversized background rects and
  page/parent containment diagnostics.
- Quality-loop tests for `layout_cluster` repair classification and destructive
  repair rejection.
- Browser validation that a failed-but-draft scene still renders on CanvasKit
  with artboard diagnostics visible.

## Slice 5: CanvasKit / Editor Interaction Polish

### Purpose

Bring the editor from "correct bounded workspace" to "high-confidence design
tool." This includes Figma/Brilliant-style selection feel, tool modes,
inspector parity, diagnostics navigation, and export readiness feedback. It
should ride with CanvasKit/editor productization, either as
`editor/canvaskit-polish-v0` or folded into CanvasKit C5/C6 after the central
workspace exists.

### Scope

Build:

- Precise selection chrome for nodes, frames, artboards, and container groups.
- Resize/rotate handles that remain visually crisp at any zoom.
- Hover outlines and click-to-focus diagnostics.
- Layer selection and artboard selection synchronization.
- Toolbar tools for select, pan, zoom, fit, frame/artboard focus, diagnostics,
  and export preview.
- Inspector state that matches selected object kind: artboard, frame, text,
  image, group, auto-layout container, slot-bound node.
- Agent/editor mode transitions that preserve the same selected artboard and
  diagnostic context.
- Diagnostics badges on artboards and selected nodes.
- Export panel polish: active profile, selected artboard(s), readiness summary,
  preview status, and copy/download actions.

Do not build:

- Loose workspace scratch object editing.
- Full Figma plugin-style tool extensibility.
- Multi-user cursors or comments.
- A new operation model for interaction edits.
- Hidden renderer-only fixes that bypass preflight or export.

### Requirements

1. Selection chrome uses the same computed/artboard geometry as export and
   hit-testing.
2. Tool state is UI state only. It must not fork scene semantics.
3. Inspector controls emit canonical operations or call existing validation/
   export APIs.
4. Diagnostics are navigable: clicking a diagnostic focuses the relevant
   artboard/node and opens the relevant panel state.
5. Export readiness is visible before export and after preview generation.
6. CanvasKit and Konva must remain behaviorally comparable until Konva is
   retired.
7. Interaction polish must not wait for loose workspace objects.

### Acceptance

- A user can select an artboard, select a child, inspect it, see diagnostics,
  fix a supported property, run preview/export, and return to the same selection
  context.
- Selection handles and overlays stay aligned under pan, zoom, and artboard
  switching.
- Diagnostics badges and panel rows focus the same underlying node/artboard.
- Export preview state makes clear whether the selected artboard is export-safe.
- The W6/CanvasKit gesture conformance suite remains green.

### Verification

- Component tests for selected-object inspector state.
- Gesture conformance tests for selection, drag, resize, rotate, and marquee.
- Playwright interaction screenshots for hover, selected node, selected
  artboard, diagnostics focus, and export-preview mode.
- CanvasKit pixel checks showing content remains nonblank and clipped while DOM
  chrome stays aligned.
- Accessibility checks for toolbar buttons, mode switch, diagnostic navigation,
  and focus-visible states.

## Slice 6: Loose Workspace Objects Later

### Purpose

Support scratch objects in the infinite workspace after the export-safe artboard
model is stable. This is useful for future creative workflows, but it is not
needed to fix the current run-trace failures.

### Scope

Build later:

- Workspace-root objects with workspace-local coordinates.
- Explicit insert/reparent into artboard action.
- Preflight warnings for loose objects that are not part of any export.
- Layer panel separation between workspace objects and artboard children.
- Optional scratch/parking-area UI.

Do not build in V0:

- Export of loose objects.
- Agent generation of loose objects by default.
- Figma-like arbitrary reparenting on drag.
- Complex overlap/auto-insert behavior.

### Rules

- Loose objects are not export-safe.
- Loose objects do not satisfy required slots.
- Loose objects are ignored by artifact export unless explicitly inserted into
  an artboard or selected as a future custom export surface.
- Agents should not produce loose objects unless the user asks for scratch
  exploration.

### Acceptance

- A document can contain scratch objects without breaking existing artboard
  export.
- Export warns or ignores loose objects deterministically.
- Moving an object into an artboard converts its coordinate context from
  workspace-local to artboard-local without visual jump.

### Verification

- Scene validation tests for loose object ownership.
- Editor tests for insert/reparent coordinate conversion.
- Export tests proving loose objects are excluded from artboard export.
- Preflight tests for loose-object warnings.

## Recommended Branch Sequence

### Branch 1: `engine/canonical-artboard-geometry-v0`

This should be first because it fixes the real engine/export failure.

Deliver:

- `PageGeometry`/normalized `PageSize` contract.
- `pt` layout unit normalization.
- Explicit custom size support in DSL/compiler if missing on this base.
- Export/preflight/editor descriptor agreement.
- Page and parent-bounds diagnostics.
- Background-like top-level rect/frame diagnostics only. This branch should
  identify oversized or artboard-covering background objects and make the
  failure explicit, but conversion into artboard fills belongs to Branch 3's
  generation/repair work.
- Failing run-trace reproduction fixtures.

Exit gate:

- A4 and custom-size fixtures prove editor/export/preflight all use the same
  layout points and physical/raster metadata.

### Branch 2: `editor/infinite-workspace-v0`

This can begin once Branch 1's DTO shape is clear. If Branch 1 is still in
flight, start with an adapter that consumes existing `PageSize` but do not merge
until the canonical geometry contract lands. This branch should implement both
Slice 2 and Slice 3: the dark editor shell plus the light infinite workspace.

Deliver:

- Dark left pages/layers panel.
- Dark right inspector/agent/export/diagnostics panel.
- Compact top artboard label and mode switch.
- Floating bottom toolbar.
- Pan/zoom workspace.
- Artboard frames, labels, active-artboard selection.
- Artboard clipping.
- Fit current/all.
- Export-selected-artboard UX.
- CanvasKit/Konva parity under the flag.

Exit gate:

- Multiple differently sized artboards are inspectable and exportable without
  changing scene dimensions.
- The editor visually matches the intended shell direction: dark side panels,
  light central workspace, bounded artboards, compact labels, and floating
  bottom toolbar.

### Branch 3: `agents/artboard-frame-generation-v0`

Deliver after Branch 1 so agent docs can point at the real geometry contract.
This can run in parallel with Branch 2 once the geometry DTO shape is stable.

Deliver:

- Knowledge docs and examples for point-based artboard-local authoring.
- Artboard-as-frame recipes.
- Layout-cluster repair classification and actuator.
- Explicit bounded `layout_cluster` repair permissions: allow p/s,
  fill/hug/fixed, auto-layout, padding, gap, wrap, root cluster sizing, and
  conversion of a background rect into an artboard/page fill only for the
  diagnosed artboard/root/parent cluster.
- Explicit `layout_cluster` repair prohibitions: no page deletion, unrelated
  node deletion, unrelated slot/brand/asset edits, or whole-scene regeneration.
- Prompt/trace evaluator checks for oversized backgrounds and parent overflow.

Exit gate:

- The appointment-card run class no longer fails from A4 unit mismatch or
  parent/child scale mismatch.

### Branch 4: `editor/canvaskit-polish-v0`

This can also be folded into CanvasKit C5/C6 if that workstream is still active.
It should not wait for loose workspace objects.

Deliver:

- Precise selection chrome, handles, hover, and diagnostics focus.
- Toolbar tool states and mode transitions.
- Inspector parity for selected artboards, frames, text, images, groups,
  auto-layout containers, and slot-bound nodes.
- Agent/editor/export/diagnostics panel state that preserves artboard context.
- Export readiness and preview affordances aligned with the right panel and
  artboard badges.

Exit gate:

- A user can inspect, fix, validate, preview, and export the selected artboard
  while selection chrome and diagnostics stay aligned under pan/zoom.
- CanvasKit gesture conformance remains green.

### Branch 5: `editor/loose-workspace-objects-v0`

Defer until the export-safe artboard workflow is stable.

Deliver:

- Workspace-root object model.
- Insert/reparent into artboard.
- Loose-object warnings and export exclusion.
- Deterministic validation/preflight warnings for loose objects.
- Guarantees that loose objects do not export and do not satisfy required
  slots unless explicitly inserted into an artboard/exportable surface.

Exit gate:

- Scratch objects are useful in the editor and cannot accidentally ship in an
  export.

## Cross-Slice Invariants

- `Scene` remains canonical.
- `Operation` remains the mutation/history surface.
- Renderer adapters are projections, not design models.
- Export dimensions come from artboard geometry, not from inner nodes.
- Child `p()`/`s()` values are artboard- or parent-local points.
- Physical units never become child coordinate units.
- Raster pixels never become renderer-specific canvas pixels.
- Viewport zoom/pan never mutates scene geometry.
- Clipping protects the editor display but never hides validation failures.
- Agent repair may broaden to a target cluster only when diagnostics identify a
  cluster; it may not silently regenerate unrelated content.

## Open Decisions

1. Should workspace artboard positions persist in `Scene` V0, or should the
   editor synthesize them from page order until loose objects exist?
   Recommendation: synthesize in V0, persist when loose objects/reordering
   require stable workspace placement.
2. Should `page` become a first-class layout frame, or should the engine keep
   `Page` as metadata and require a root `artboard` child?
   Recommendation: long-term page/artboard should be a bounded parent frame;
   short-term root `artboard` child is acceptable if it avoids destabilizing
   current `Page` operations.
3. Should display labels round A4 to `595 x 842 pt` while internal geometry keeps
   `595.276 x 841.890 pt`?
   Recommendation: yes. Use exact internal values with epsilon tests; show
   rounded values in agent-facing examples only when precision is irrelevant.
4. Should digital `px` inputs be stored as `pt` layout values numerically equal
   to pixels?
   Recommendation: yes. Store the original unit and raster defaults so export
   intent remains explicit.

## Completion Definition

This plan is complete when:

- A4, Letter, square social, landscape social, portrait social, email header,
  and custom print surfaces all share one canonical point layout model.
- The editor shows those surfaces as bounded artboards on an infinite workspace.
- The editor chrome follows the intended product direction: dark side panels,
  compact top artboard state, floating bottom toolbar, and a light central
  workspace.
- Exported SVG/PNG/PDF dimensions match the selected artboard's geometry and
  export profile.
- Preflight catches page/artboard and parent containment overflow before export.
- The agent generates artboard-local layouts using parent fills and auto-layout
  recipes rather than oversized background rectangles.
- Selection, inspector, agent, diagnostics, and export-preview interactions keep
  the same active artboard context and stay aligned under pan/zoom.
- The appointment-card run failure class is eliminated or converted into clear,
  targeted diagnostics that the layout-cluster repair path can address.
