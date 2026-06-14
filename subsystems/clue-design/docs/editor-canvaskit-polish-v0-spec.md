# Editor CanvasKit Polish V0 Spec

Date: 2026-06-14
Branch: `editor/canvaskit-polish-v0`
Base dependency: `integration/artboard-workspace-v0`
Status: specification

## Purpose

This branch defines and implements the first polish pass after the canonical
artboard geometry, infinite workspace, and artboard-frame generation branches
have converged. The product now has the right high-level shape:

- canonical page/artboard layout geometry in points;
- dark editor shell with a medium dark grey infinite workspace;
- blank white bounded artboards as the drawable/exportable surfaces;
- selected-artboard export and diagnostics flows;
- CanvasKit and Konva workspace parity behind the renderer flag;
- agent guidance that treats artboards as bounded parent frames.

The remaining problem is editor confidence. A user can see the workspace and
export an artboard, but the next product step is making inspection, repair,
validation, preview, and export feel precise and trustworthy under CanvasKit.
This branch should make the editor behave like one coherent design tool surface
instead of a set of mostly-correct panels around a renderer.

The key outcome is:

> A user can inspect, fix, validate, preview, and export the selected artboard
> while selection chrome, handles, diagnostics, and export readiness stay aligned
> under pan and zoom.

## Source Alignment

This spec is constrained by these current source documents and landed branch
contracts:

- `docs/artboard-workspace-geometry-plan.md`
- `docs/editor-infinite-workspace-v0-spec.md`
- `docs/editor-infinite-workspace-v0-implementation-plan.md`
- `docs/wave-3-canvaskit-editor-plan.md`
- `docs/phase-f-editor-export-productization.md`
- `docs/phase-f-parity-acceptance-matrix.md`
- `.codex/memory/workstreams/engine-canonical-artboard-geometry-v0.md`
- `.codex/memory/workstreams/editor-infinite-workspace-v0.md`
- `.codex/memory/workstreams/agents-artboard-frame-generation-v0.md`
- `.codex/memory/workstreams/integration-artboard-workspace-v0.md`
- `.codex/memory/workstreams/editor-canvaskit-canvas-v0.md`
- `.codex/memory/workstreams/phase-f-editor-export-productization-v0.md`
- `reference_docs/ABM-Design-Engine-Temporary-Spec.md`
- `reference_docs/Brilliant-Reverse-Engineering-Report.md`
- `../design/reference_docs/Brilliant-vs-Lumen-Product-Gap-Analysis.md`

The invariant from those sources is unchanged:

- `Scene` is the canonical design model.
- `Operation` is the canonical mutation/history model.
- DSL is an authoring and repair projection, not the source of truth.
- Workspace placement, pan, zoom, mode, and tool state are editor UI state.
- Page/artboard dimensions and child geometry are canonical scene data.
- Export, preview, diagnostics, editor rendering, and agent repair must converge
  through the same scene, computed geometry, page/artboard geometry, Brand Kit
  resolution, asset refs, and diagnostics.

This branch must not create a new scene model, a renderer-owned coordinate
model, or an export path that bypasses canonical preflight/export diagnostics.

## Problem

### 1. CanvasKit has the rendering substrate, but not enough product polish

The CanvasKit branch already rebuilt the hard substrate: draw descriptors,
CanvasKit stage lifecycle, hit-testing, gesture reducer, resize/rotate math,
DOM/SVG selection overlay, SkParagraph measurement, text edit overlay, and
renderer flag plumbing. The integration branch then taught both renderers about
the medium dark grey infinite workspace and bounded artboards.

That still leaves a product gap. The editor needs polished, predictable behavior
around:

- selection chrome precision under workspace pan and zoom;
- hover and active-target feedback;
- handle affordances and disabled-handle explanations;
- tool-state transitions between select, pan, text editing, diagnostics, export,
  and agent mode;
- active-artboard context preservation across panels and renderer modes;
- inspector controls that explain and edit the selected object class correctly;
- diagnostics that focus the exact artboard/node/cluster needing repair;
- export readiness and preview affordances that match the selected artboard.

Without this pass, the editor can render and export, but users still have to
infer too much from raw panels and diagnostics.

### 2. CanvasKit is immediate-mode, so chrome alignment is a first-class risk

Konva used a retained scene graph. CanvasKit draws pixels and then forgets the
scene. In Lumen, the CanvasKit content surface and the DOM/SVG overlay must stay
in lockstep across these coordinate spaces:

```text
screen px
  -> workspace coordinates
  -> artboard-local canonical points
  -> computed node geometry
  -> descriptor/render coordinates
```

The existing design puts selection chrome in a DOM/SVG overlay above the
CanvasKit content surface. That is the right approach for V0: it keeps chrome
crisp, lets DOM handle hit areas, and avoids wasm redraws for hover/selection
changes. The polish branch must make this seam production-credible.

### 3. Diagnostics and export readiness need to feel artboard-native

The integration branch already groups diagnostics by artboard and maps selected
artboard export to `pageIds: [activeArtboardId]`. The next branch should make
diagnostics and export readiness part of the selected-artboard workflow:

- artboard badges summarize readiness without opening raw diagnostics;
- clicking a diagnostic keeps artboard context and focuses the target;
- the inspector shows issues relevant to the current page/node/cluster;
- export preview explains whether the selected artboard is ready, warning-only,
  blocked, or still missing preview artifacts;
- export controls preserve selected-artboard state across editor, agent,
  export, and diagnostics modes.

### 4. Left panel needs the intended hierarchy, not only page metadata

The product direction is a dark left rail with a page/artboard list and size
metadata at the top, plus the layer hierarchy tree below it. Current work keeps
artboard list and size metadata and includes an active-artboard layer tree. This
branch should polish that combined left rail so users can navigate pages and
nodes from one coherent tree-like panel.

## Target State

The target editor surface is:

```text
dark left panel        medium dark grey workspace       dark right panel
pages + sizes          blank white artboard frame       inspector/agent/export
layer tree             precise selection chrome         diagnostics

compact top active-artboard label + mode switch
floating bottom toolbar for tools, zoom, fit, diagnostics, export
```

The target user workflow is:

1. Select an artboard from the left panel or by clicking it in the workspace.
2. Select a node, group, text object, image, auto-layout container, or slot-bound
   node on the artboard.
3. See selection chrome, hover affordances, handles, and disabled-handle reasons
   aligned with the visual object at any pan/zoom.
4. Inspect the selected object in the right panel without losing active-artboard
   context.
5. See focused diagnostics for the selected object, parent cluster, active
   artboard, or export readiness state.
6. Apply manual fixes through canonical operations.
7. Validate and export preview the selected artboard.
8. Confirm export readiness, sidecar scope, diagnostics, and artifact preview.
9. Export the selected artboard or all artboards with consistent state.

## Scope

This branch owns these deliverables.

### 1. Selection Chrome, Handles, Hover, And Focus

The editor should provide precise and legible CanvasKit selection feedback:

- selected node outline aligned with rendered content under pan and zoom;
- active artboard outline/badge aligned with workspace placement;
- hover outline for hit-test target;
- container child outlines for selected frames/groups/auto-layout containers;
- resize handles for directly geometry-editable nodes;
- rotate handle where supported by existing operations/math;
- marquee feedback;
- disabled or suppressed handles for locked, layout-managed, or otherwise
  non-direct-editable nodes;
- clear notice or tooltip explaining why handles are disabled;
- diagnostics focus overlay or badge for nodes/artboards with blocking issues;
- no content redraw solely because hover or selection changed.

The overlay remains DOM/SVG in V0. CanvasKit draws scene content and artboard
content; the overlay draws editor chrome.

### 2. Toolbar Tool States And Mode Transitions

The compact top context and floating bottom toolbar must behave as one state
machine:

- top mode switch: inspector, agent, export, diagnostics;
- bottom tools: select, pan, zoom, fit current, fit all, diagnostics, export;
- text editing overlay: enters and exits without corrupting selection or
  pan/zoom state;
- export preview/compare mode: can open from toolbar or right panel without
  resetting active artboard;
- diagnostics mode: can focus an issue without switching to the wrong artboard
  or clearing selection;
- agent mode: preserves active artboard, selected node, and relevant diagnostics
  in the prompt context;
- renderer flag transitions do not change selected node, active artboard,
  workspace viewport, or export panel state.

Tool state is editor UI state. It must not persist into `Scene`.

### 3. Inspector Parity

The inspector should be artboard-aware and object-class-aware for:

- selected artboards/pages;
- frames and groups;
- text nodes;
- image nodes;
- auto-layout containers;
- ordinary rect/vector/path-like nodes supported by the current scene model;
- slot-bound nodes;
- locked nodes;
- layout-managed children;
- brand-token-backed style values where current token plumbing supports them.

Inspector parity does not mean every possible Figma control exists. It means
the selected object's available canonical operations are visible, disabled
controls explain why they are disabled, and diagnostics near the controls match
the selected subject.

For V0, the inspector may keep existing component structure, but the user should
not have to guess whether a field edits scene data, export metadata, layout
metadata, slot metadata, or preview-only UI state.

### 4. Panel State And Artboard Context

Right-panel surfaces must preserve selected-artboard context:

- Inspector mode keeps selected node/artboard context.
- Agent mode receives active artboard, selected node, and current diagnostics.
- Export mode preserves selected profile, selected/all artboards scope, draft
  profile edits, and latest result.
- Diagnostics mode preserves active artboard and selected subject focus.
- Switching between modes does not reset workspace viewport, selected node,
  active artboard, export profile state, or diagnostics focus.
- Diagnostic subject actions activate the owning artboard and select the target
  node when one exists.

### 5. Export Readiness And Preview Affordances

The branch should make selected-artboard export readiness obvious:

- artboard badges summarize ready/warning/error/unknown state;
- export panel labels consistently say selected artboard or all artboards;
- export preview names the active artboard and profile;
- sidecar/artifact rows confirm page/artboard IDs in scope;
- preview readiness derives from artifact presence, export status, parity
  result, and diagnostics;
- warning-only results are reviewable but labeled honestly;
- error/blocking diagnostics are visible from the export surface;
- selected-artboard export still maps to `pageIds: [activeArtboardId]`;
- all-artboards export still maps to all scene page IDs.

Preview generation may still proceed with diagnostics for debug/inspection, as
Phase F established. Readiness and approval remain fail-closed when errors or
missing artifacts exist.

### 6. CanvasKit / Konva Parity Under The Flag

CanvasKit is the focus, but this branch must not regress the flag period:

- both renderers consume the same `WorkspaceModel`;
- both renderers consume the same `WorkspaceViewport`;
- both renderers keep active-artboard selection semantics;
- both renderers clip artboard content;
- both renderers keep selected-artboard export UX aligned;
- CanvasKit gesture conformance remains green;
- Konva remains a fallback unless a separate product decision retires it.

## Non-Goals

This branch does not own:

- changing canonical artboard geometry or page metadata DTOs;
- migrating legacy non-pt scenes;
- introducing loose workspace objects outside artboards;
- supporting multiple drawable frames per page;
- changing DSL grammar for page/artboard creation;
- changing agent layout-cluster repair permissions;
- implementing new export formats;
- adding full Figma-style constraints, components, variants, or plugins;
- replacing all right-panel components with a new design system;
- deleting Konva or flipping the renderer default permanently;
- browser-rendered smoke with a new browser plugin unless explicitly scheduled
  for this branch's verification session.

## Current Starting Points

The current branch contains these relevant surfaces:

- `apps/editor/src/components/EditorApp.tsx`
  - owns scene state, active page/artboard, selected node, workspace viewport,
    workspace tool, right-panel mode, diagnostics, export result, agent state,
    and panel composition.
- `apps/editor/src/components/canvas/EditorCanvas.tsx`
  - switches between Konva and CanvasKit, deriving a shared `WorkspaceModel`.
- `apps/editor/src/components/canvas/CanvasKitCanvas.tsx`
  - CanvasKit host, workspace pan/zoom, tool buttons, text measurement pass,
    pointer handling, hit-testing, selection overlay, and text edit overlay.
- `apps/editor/src/components/canvas/CanvasKitStage.tsx`
  - draws CanvasKit artboards and clipped page content.
- `apps/editor/src/components/canvas/SelectionOverlay.tsx`
  - DOM/SVG selection box, handles, marquee, container labels.
- `apps/editor/src/engine/workspaceLayout.ts`
  - derived artboard placements and artboard-level diagnostics summaries.
- `apps/editor/src/engine/workspaceViewport.ts`
  - pan, zoom, fit current/all, coordinate conversions.
- `apps/editor/src/components/PageRail.tsx`
  - artboard list, size labels, status dots, add/duplicate/remove.
- `apps/editor/src/components/LayerPanel.tsx`
  - active-artboard layer hierarchy.
- `apps/editor/src/components/InspectorPanel.tsx`
  - page/artboard, node, layout, style, slot, and diagnostics controls.
- `apps/editor/src/components/ExportPanel.tsx`
  - export profiles, selected/all artboard scope, artifacts, sidecars, print
    guardrails, diagnostics.
- `apps/editor/src/components/ExportPreviewSurface.tsx`
  - export preview readiness and parity/export diagnostics.
- `apps/editor/src/components/ValidationPanel.tsx`
  - validation and render diagnostics grouped by focus/artboard.
- `apps/editor/src/engine/canvaskitGestures.ts`,
  `gestureMachine.ts`, `transformerMath.ts`
  - gesture capture, operation conversion, handle math, conformance substrate.

The spec should be implemented by improving these seams, not by bypassing them.

## Required UX Behavior

### Active Artboard

- There is always one active artboard when any page exists.
- Clicking an artboard activates it.
- Clicking a node in an inactive artboard activates that artboard and selects the
  hit node in the same interaction when hit-testing succeeds.
- Clicking empty workspace clears selected node without changing page geometry.
- Clicking empty area inside the active artboard clears selected node but keeps
  the artboard active.
- Fit current uses the active artboard's workspace rect.
- Fit all uses the workspace model bounds.

### Selection

- Node selection is by canonical `NodeId`.
- Page/artboard selection is by canonical `PageId`.
- Selection chrome uses computed/render bounds, not stale authored values, when
  computed geometry is available.
- Selection of layout-managed children shows constrained affordances.
- Locked nodes can be selected and inspected but not transformed.
- Selection changes sync the left layer tree, inspector focus, and diagnostics
  focus.

### Hover

- Hover should show the deepest hit-test target that would be selected by click.
- Hover must not apply operations.
- Hover must not trigger CanvasKit content redraw.
- Hover should degrade gracefully when WASM hit-testing is unavailable.

### Text Editing

- Double-clicking text enters the DOM text edit overlay.
- The overlay aligns to the rendered text box under pan/zoom.
- Blur or commit applies `updateTextNode`.
- Escape cancels.
- Text editing should keep the active artboard and selected node stable.

### Diagnostics

- Diagnostics are grouped by document, artboard, node, slot, asset, and focused
  subject where possible.
- Artboard badges summarize current diagnostics status.
- Clicking a diagnostic activates the owning artboard and selected node, if any.
- Diagnostics mode keeps diagnostics visible after focusing the subject.
- Inspector mode shows focused diagnostics near relevant controls.
- Export mode includes export and preflight diagnostics relevant to the selected
  export scope.

### Export

- Export selected artboard uses only the active artboard/page ID.
- Export all artboards uses all current scene page IDs.
- Export profile state survives mode switches.
- The latest export result remains visible until a new export invalidates it or
  the underlying scene/profile/artboard scope changes enough to mark it stale.
- Export preview and compare views should not reset the workspace viewport.

## Technical Contract

### Coordinate Spaces

All code touched by this branch should name coordinate-space conversions
explicitly. The intended flow is:

```text
PointerEvent client coordinates
  -> shell-local screen coordinates
  -> workspace coordinates via WorkspaceViewport
  -> artboard-local descriptor coordinates via WorkspaceArtboard.workspaceRect
  -> canonical scene coordinates via page unit scale
  -> hit-test / gesture reducer / operation builder
```

Rendering flows the opposite direction:

```text
Scene + computed geometry
  -> page/node descriptors
  -> artboard-local descriptor coordinates
  -> workspace placement
  -> WorkspaceViewport screen placement
  -> CanvasKit content surface + DOM/SVG editor chrome
```

No new code should infer artboard-local geometry from physical print metadata.
The layout size is canonical; physical/raster metadata belongs to export
profiles and page source/output metadata.

### Mutation Surface

All edits commit through existing canonical operations, including but not
limited to:

- `updatePageName`
- `updatePageSize`
- `updatePageBackground`
- `updatePageSafeArea`
- `updatePageBleed`
- `updateNodeTransform`
- `updateNodeSize`
- `updateNodeLayout`
- `updateAutoLayoutNode`
- `updateAutoLayoutAlignment`
- `updateTextNode`
- `updateNodeFills`
- `updateNodeStrokes`
- `updateNodeLocked`
- `moveNodeToParent`
- export profile upsert/remove operations

The branch must not mutate raw scene JSON from UI controls.

### Renderer Responsibilities

CanvasKit:

- draw artboard/page content;
- clip children to artboard bounds;
- use shared draw descriptors;
- use shared `WorkspaceModel` and `WorkspaceViewport`;
- provide CanvasKit text measurement for layout convergence when available;
- delegate chrome to DOM/SVG overlay;
- keep the gesture-to-operation path canonical.

DOM/SVG overlay:

- draw selection/hover/marquee/handles/snap/focus chrome;
- stay aligned with CanvasKit content under pan/zoom;
- provide accessible handle hit areas where needed;
- avoid becoming a second renderer for scene content.

Konva:

- remain functional under the flag period;
- consume the same workspace model and viewport;
- preserve existing operation-level conformance.

### State Ownership

Persisted scene state:

- pages/artboards;
- nodes and tree;
- transforms and sizes;
- layout fields;
- fills, strokes, text, images, slots;
- Brand Kit refs and export profile metadata;
- operation history through existing model.

Editor-only state:

- workspace viewport;
- selected tool;
- active right-panel mode;
- view mode: canvas, export preview, compare;
- hover target;
- marquee in progress;
- live transform preview;
- export panel draft fields not yet saved as a profile;
- diagnostics focus and UI expansion state.

## Implementation Slices

### P0: Baseline Audit And Test Anchors

Purpose: lock the current behavior before polish changes.

Tasks:

- Audit current CanvasKit and Konva workspace behavior.
- Identify the smallest set of component and engine tests that cover selection,
  tool states, panel modes, diagnostics focus, and export scope.
- Add missing regression tests for any current behavior that this branch must
  preserve.

Suggested tests:

- `EditorApp.test.tsx`
- `EditorCanvas.test.tsx`
- `canvaskitGestures.test.ts`
- `canvaskitConformance.test.ts`
- `gestureConformance.test.ts`
- `workspaceLayout.test.ts`
- `workspaceViewport.test.ts`
- `exportRunner.test.ts`
- `ExportPreviewSurface.test.tsx`
- `InspectorPanel.test.tsx`
- `ValidationPanel` coverage where present or through `EditorApp`.

Exit gate:

- Current behavior is covered before visual/state changes land.

### P1: Selection Chrome And Hover Precision

Tasks:

- Add hover target state and overlay rendering.
- Align selection overlay to all artboards, not only the active page origin, when
  needed for diagnostics/hover focus.
- Verify handle positions under zoom, pan, and rotated boxes.
- Add disabled-handle explanation for locked/layout-managed selections.
- Ensure overlay updates do not force CanvasKit content redraw.
- Keep selection chrome legible on blank white artboards and on the medium dark
  grey workspace.

Exit gate:

- Selection, hover, handles, and diagnostics focus align with rendered content
  under pan/zoom for CanvasKit.
- Existing CanvasKit gesture conformance remains green.

### P2: Toolbar And Mode State Machine

Tasks:

- Make tool and panel modes explicit enough to test as a state machine.
- Ensure select/pan/text edit/export preview/diagnostics transitions preserve
  artboard and selection context.
- Add active/disabled/pressed states and tooltips for compact icon controls.
- Ensure toolbar dimensions remain stable as zoom/status text changes.
- Avoid text overflow in compact controls.

Exit gate:

- Mode switches do not clear active artboard, selected node, workspace viewport,
  or export panel state.

### P3: Inspector Parity And Focused Diagnostics

Tasks:

- Audit inspector behavior for artboard, frame/group, text, image, auto-layout,
  layout-managed child, locked node, and slot-bound node selections.
- Add or clarify missing object-class headings, disabled reasons, and operation
  boundaries.
- Show focused diagnostics near relevant controls for selected node/artboard.
- Preserve page/artboard context in document-level inspector state.

Exit gate:

- A selected artboard or node has an understandable inspector surface and
  focused diagnostics.

### P4: Export Readiness And Preview Affordances

Tasks:

- Make export readiness visible from artboard badges, export panel, and preview.
- Clearly label selected-artboard versus all-artboards scope.
- Preserve export panel state through mode switches and diagnostic navigation.
- Mark stale previews when scene/profile/scope changes invalidate them, if this
  can be done cleanly without a larger cache invalidation rewrite.
- Ensure export diagnostics activate relevant artboard/node subjects.

Exit gate:

- A user can validate, preview, understand readiness, and export the selected
  artboard without guessing what scope is active.

### P5: CanvasKit/Konva Parity And Final Polish

Tasks:

- Re-run renderer parity tests under both paths.
- Keep CanvasKit gesture conformance green.
- Ensure Konva fallback keeps the same artboard context and export semantics.
- Update docs/memory with any user-visible decisions, deferred items, or
  verification gaps.

Exit gate:

- The branch passes the full non-browser verification matrix.
- Browser-rendered smoke is either completed in the approved browser-plugin
  session or explicitly documented as deferred by user instruction.

## Acceptance Criteria

This branch is complete when all of the following are true:

- The editor retains a dark left panel, dark right panel, and medium dark grey
  central infinite workspace.
- Artboards remain blank white bounded drawable frames unless the scene page
  background says otherwise.
- The left panel keeps page/artboard list and size metadata and shows the layer
  hierarchy tree below it.
- Selecting an artboard or node preserves active-artboard context across
  inspector, agent, export, and diagnostics modes.
- CanvasKit selection chrome, handles, hover, marquee, and diagnostics focus
  align with the rendered object under pan and zoom.
- Locked and layout-managed selections communicate why direct handles are
  unavailable.
- Inspector controls are coherent for selected artboards, frames/groups, text,
  images, auto-layout containers, and slot-bound nodes.
- Export readiness is visible before download.
- Selected-artboard export scope is explicit and maps to the active page ID.
- Export preview and compare surfaces preserve artboard context.
- Diagnostics can focus the relevant artboard/node without losing diagnostics
  mode or clearing selection unexpectedly.
- CanvasKit and Konva consume the same workspace model and viewport semantics
  during the flag period.
- CanvasKit gesture conformance remains green.
- No implementation creates a second scene model, bypasses operations, or uses
  physical mm/in metadata as child layout coordinates.

## Verification Matrix

Minimum non-browser verification:

```text
npm --prefix apps/editor test -- --run src/components/__tests__/EditorApp.test.tsx
npm --prefix apps/editor test -- --run src/components/canvas/__tests__/EditorCanvas.test.tsx
npm --prefix apps/editor test -- --run src/engine/__tests__/workspaceLayout.test.ts src/engine/__tests__/workspaceViewport.test.ts
npm --prefix apps/editor test -- --run src/engine/__tests__/canvaskitGestures.test.ts src/engine/__tests__/canvaskitConformance.test.ts src/engine/__tests__/gestureConformance.test.ts
npm --prefix apps/editor test -- --run src/engine/__tests__/exportRunner.test.ts src/engine/__tests__/exportPreviewApproval.test.ts
npm --prefix apps/editor test -- --run src/components/__tests__/InspectorPanel.test.tsx src/components/__tests__/AgentChatPanel.test.tsx
npm --prefix apps/editor run lint
git diff --check
```

Recommended broader verification before merge:

```text
npm --prefix apps/editor test -- --run --testTimeout 20000
cargo test --workspace
/Users/aryankeshri/Documents/brilliant-design/.venv/bin/python -m pytest apps/api/tests/test_api.py -q
/Users/aryankeshri/Documents/brilliant-design/.venv/bin/python -m pytest apps/api/tests/test_phase_g_conformance.py -q
```

Browser/plugin verification, when explicitly scheduled:

- default renderer and CanvasKit renderer both show nonblank editor shell;
- medium dark grey infinite workspace is visible;
- artboards are blank white bounded frames;
- page/artboard list and layer tree are visible in the left rail;
- selection chrome and handles align at desktop and narrow widths;
- pan, zoom, fit current, and fit all work;
- diagnostics focus an artboard/node and keep diagnostics context;
- selected-artboard export sends only the active page ID;
- export preview/compare show the selected artboard artifact;
- console has no stable app/runtime errors.

## Risks And Mitigations

### Risk: Overlay and CanvasKit content drift

Mitigation:

- centralize coordinate conversions;
- test overlay boxes under pan/zoom/rotation;
- avoid duplicated scale/origin math inside components.

### Risk: Diagnostics navigation fights mode preservation

Mitigation:

- define diagnostic subject action behavior explicitly;
- test diagnostics mode after focus actions;
- keep selected artboard and selected node independent from panel mode.

### Risk: Inspector becomes a mixed bag of scene and UI state

Mitigation:

- label operation-backed fields clearly in code and tests;
- keep UI-only expansion/draft state outside scene;
- route all committed edits through operations.

### Risk: Export preview looks usable even when blocked

Mitigation:

- preserve Phase F behavior: preview artifacts can be generated for inspection,
  but approval/readiness fails closed on errors, missing artifacts, failed export,
  or parity mismatch;
- show warning/error state in artboard badge and export preview.

### Risk: CanvasKit polish breaks Konva fallback

Mitigation:

- keep shared workspace model and viewport helpers renderer-agnostic;
- keep renderer-specific polish behind components, not scene contracts;
- run both gesture and CanvasKit conformance tests.

## Deferred Follow-Ups

These are intentionally outside V0:

- loose workspace objects that are not inside artboards;
- multiple drawable frames inside one scene page;
- component/variant systems;
- full drag insertion for auto-layout containers;
- alpha-accurate raster/image hit testing;
- rich text editing beyond current text node support;
- final Konva retirement decision;
- final browser-plugin screenshot/canvas-pixel QA if not explicitly scheduled in
  this branch session.

## Definition Of Done

The branch is done when the code and tests prove this statement:

> For a selected artboard, the editor can keep artboard context stable while the
> user selects and fixes nodes, reviews focused diagnostics, previews export
> readiness, and exports the artifact; CanvasKit chrome remains aligned under
> pan/zoom and the canonical operation/scene/export contracts remain intact.
