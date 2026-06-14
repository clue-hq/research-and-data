# Editor CanvasKit Polish V0 Implementation Plan

Date: 2026-06-14
Branch: `editor/canvaskit-polish-v0`
Worktree: `/Users/aryankeshri/Documents/brilliant-design/editor-canvaskit-polish-v0`
Primary spec: `docs/editor-canvaskit-polish-v0-spec.md`
Base dependency: `integration/artboard-workspace-v0`
Status: implementation plan

## Purpose

This document turns `docs/editor-canvaskit-polish-v0-spec.md` into an execution
plan for the current worktree and branch. It is deliberately detailed because
this branch is a product-polish bridge between several already-landed contracts:

- canonical point-based artboard geometry;
- medium dark grey infinite workspace with blank white bounded artboards;
- CanvasKit/Konva workspace parity under the renderer flag;
- selected-artboard export UX;
- artboard/grouped diagnostics;
- agent artboard-frame generation and bounded repair guidance;
- future ABM personalization through slot-bound templates.

The implementation should not chase a vague "make the editor nicer" goal. It
should make the selected-artboard workflow precise:

> select artboard -> select object -> inspect/fix -> review diagnostics ->
> preview export -> export selected artboard

The branch is successful when a user can follow that loop while CanvasKit
selection chrome, handles, hover, diagnostics focus, and export readiness remain
aligned under pan and zoom.

## Source Inputs

Read these before implementation work:

- `docs/editor-canvaskit-polish-v0-spec.md`
- `docs/artboard-workspace-geometry-plan.md`
- `docs/editor-infinite-workspace-v0-spec.md`
- `docs/editor-infinite-workspace-v0-implementation-plan.md`
- `docs/wave-3-canvaskit-editor-plan.md`
- `docs/phase-f-editor-export-productization.md`
- `docs/phase-f-parity-acceptance-matrix.md`
- `docs/slot-personalization-binding-architecture.md`
- `.codex/memory/workstreams/editor-canvaskit-polish-v0.md`
- `.codex/memory/workstreams/integration-artboard-workspace-v0.md`
- `.codex/memory/workstreams/editor-infinite-workspace-v0.md`
- `.codex/memory/workstreams/editor-canvaskit-canvas-v0.md`
- `.codex/memory/workstreams/phase-f-editor-export-productization-v0.md`
- `reference_docs/ABM-Design-Engine-Temporary-Spec.md`
- `reference_docs/Brilliant-Reverse-Engineering-Report.md`
- `../design/reference_docs/Brilliant-vs-Lumen-Product-Gap-Analysis.md`

The key architectural rule from those sources:

```text
Scene + Operation remain canonical.
Editor, renderer, diagnostics, preview, and export are projections.
```

No implementation slice may create a second scene model, silently mutate raw
scene JSON, persist workspace placement, or use physical print metadata as child
layout coordinates.

## Current Code Surfaces

### App And State

- `apps/editor/src/components/EditorApp.tsx`
  - Owns scene state, active page/artboard, selected node, workspace viewport,
    selected tool, right-panel mode, diagnostics, export result, agent state,
    keyboard shortcuts, and panel composition.
  - Diagnostic subject routing already handles `page`, `node`, `slot`, and
    `asset` subjects.
  - Export panel state is already lifted into `EditorApp`.

- `apps/editor/src/components/canvas/EditorCanvas.tsx`
  - Builds `WorkspaceModel` and switches between Konva and CanvasKit using the
    existing renderer flag.
  - This is the correct seam for parity assertions.

### CanvasKit Path

- `apps/editor/src/components/canvas/CanvasKitCanvas.tsx`
  - Hosts CanvasKit content, workspace pan/zoom, select/hand tools, fit
    current/all, inactive artboard activation, gesture dispatch, text edit
    overlay, and SkParagraph measurement injection.

- `apps/editor/src/components/canvas/CanvasKitStage.tsx`
  - Draws the medium dark grey workspace backdrop, artboard frames, clipped
    artboard content, and active artboard border.
  - Must remain scene-content focused; editor chrome should stay out of this
    component unless there is a strong rendering reason.

- `apps/editor/src/components/canvas/SelectionOverlay.tsx`
  - Draws selected node outline, container child outlines, label, resize handles,
    rotate handle, and marquee.
  - This branch should extend this overlay rather than drawing chrome in
    CanvasKit.

- `apps/editor/src/components/canvas/TextEditOverlay.tsx`
  - DOM text edit overlay; must stay aligned with CanvasKit under pan/zoom.

### Workspace Model

- `apps/editor/src/engine/workspaceLayout.ts`
  - Derives artboards from scene pages.
  - Computes workspace rects, workspace bounds, active artboard, diagnostics
    summaries, and artboard-local/workspace conversions.

- `apps/editor/src/engine/workspaceViewport.ts`
  - Owns viewport pan/zoom, fit, clamp, and screen/workspace conversions.

### Interaction Model

- `apps/editor/src/engine/canvaskitGestures.ts`
  - Converts CanvasKit gesture actions into canonical operations.

- `apps/editor/src/engine/gestureMachine.ts`
  - Pure gesture reducer for select, drag, resize, rotate, marquee.

- `apps/editor/src/engine/transformerMath.ts`
  - Handle positions, rotation math, resize math.

- `apps/editor/src/engine/canvasSelection.ts`
  - Direct geometry eligibility, container selection geometry, disabled-selection
    notices.

### Panels

- `apps/editor/src/components/PageRail.tsx`
  - Artboard list, size labels, diagnostic dots, add/duplicate/remove.

- `apps/editor/src/components/LayerPanel.tsx`
  - Active artboard layer tree, selection sync, reorder operations.

- `apps/editor/src/components/InspectorPanel.tsx`
  - Page/artboard inspector, node inspector, layout/style/text/slot controls,
    focused diagnostics.

- `apps/editor/src/components/SlotInspector.tsx`
  - Existing slot summary and selected slot controls.

- `apps/editor/src/components/ValidationPanel.tsx`
  - Focused diagnostics, grouped diagnostics, subject buttons.

- `apps/editor/src/components/ExportPanel.tsx`
  - Export profile controls, selected/all artboards, artifacts, sidecars,
    export diagnostics, readiness warnings.

- `apps/editor/src/components/ExportPreviewSurface.tsx`
  - Preview approval summary and parity/export diagnostics.

- `apps/editor/src/components/AgentChatPanel.tsx`
  - Agent prompt context: active page, selected node, diagnostics.

## Design Contracts To Preserve

### Canonical Scene And Operation Contract

Committed edits must continue to flow through operation builders and the WASM
engine path. UI changes may produce editor-only state, but persisted changes
must use canonical operations such as:

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
- `upsertExportProfile`
- `removeExportProfile`
- slot bind/unbind/upsert operations where existing UI already exposes them.

### Coordinate Contract

All touched interaction and chrome code should name the coordinate space it is
using. The intended path is:

```text
browser client point
  -> canvas-shell local screen point
  -> workspace point via WorkspaceViewport
  -> artboard-local descriptor point via WorkspaceArtboard.workspaceRect
  -> canonical scene point via page unitScale
  -> hitTest / gestureReducer / operation builder
```

Rendering and chrome alignment flow back:

```text
Scene + computed geometry
  -> page/node descriptors
  -> artboard-local descriptor geometry
  -> workspace placement
  -> screen placement via WorkspaceViewport
  -> CanvasKit content + DOM/SVG chrome
```

Implementation rule: do not duplicate math ad hoc in multiple components.
Introduce small helper functions when the same conversion appears in two places.

### Slot/Personalization Contract

The polish branch should prepare seams for future X-ray review without
implementing the full personalization product:

- recognize existing slot-bound node state;
- allow selection/chrome models to carry optional slot metadata;
- preserve `DiagnosticSubject.kind === "slot"` handling;
- do not make sidebar slot browsing the primary UX;
- do not add content-schema import, inline merge fields, or X-ray mode in this
  branch.

## Implementation Strategy

Work in small reviewable commits. Each phase below is a checkpoint that can be
committed independently if it leaves tests green.

Recommended branch checkpoints:

1. Plan document.
2. Baseline tests and helper inventory.
3. Shared chrome/focus model helpers.
4. CanvasKit overlay hover and disabled-handle polish.
5. Toolbar and mode state hardening.
6. Inspector parity and slot-bound selection hooks.
7. Export readiness and diagnostics focus polish.
8. Final parity, docs, and memory update.

## Phase P0: Baseline Audit And Test Anchors

### Goal

Create a reliable before/after harness so visual and state polish does not
silently regress existing editor behavior.

### Files To Inspect

- `apps/editor/src/components/__tests__/EditorApp.test.tsx`
- `apps/editor/src/components/canvas/__tests__/EditorCanvas.test.tsx`
- `apps/editor/src/components/canvas/__tests__/SelectionOverlay.test.tsx`
- `apps/editor/src/components/__tests__/InspectorPanel.test.tsx`
- `apps/editor/src/components/__tests__/ExportPreviewSurface.test.tsx`
- `apps/editor/src/engine/__tests__/workspaceLayout.test.ts`
- `apps/editor/src/engine/__tests__/workspaceViewport.test.ts`
- `apps/editor/src/engine/__tests__/canvaskitGestures.test.ts`
- `apps/editor/src/engine/__tests__/canvaskitConformance.test.ts`
- `apps/editor/src/engine/__tests__/gestureConformance.test.ts`
- `apps/editor/src/engine/__tests__/canvasSelection.test.ts`
- `apps/editor/src/engine/__tests__/renderAdapter.test.ts`
- `apps/editor/src/engine/__tests__/exportPreviewApproval.test.ts`
- `apps/editor/src/engine/__tests__/exportRunner.test.ts`

### Tasks

1. Inventory existing assertions for:
   - active artboard preservation;
   - selected node preservation;
   - workspace viewport preservation;
   - export panel state preservation;
   - diagnostic subject navigation;
   - slot diagnostic navigation;
   - CanvasKit/Konva renderer switch props;
   - selection overlay handles and hidden handles;
   - gesture conformance.

2. Add missing tests only for behavior that already exists and must survive:
   - clicking diagnostics keeps Diagnostics mode;
   - selected-artboard export still maps to active page ID;
   - slot diagnostics still navigate to the first bound node;
   - renderer switch receives same `WorkspaceModel`;
   - CanvasKit overlay hidden handles still render the selected outline.

3. Do not implement polish features in P0 unless a test cannot be written
   without exposing a tiny helper.

### Expected Output

- A short audit note in the phase commit or memory entry naming tests that cover
  the baseline.
- Additional regression tests if gaps exist.

### Verification

```text
npm --prefix apps/editor test -- --run src/components/__tests__/EditorApp.test.tsx
npm --prefix apps/editor test -- --run src/components/canvas/__tests__/EditorCanvas.test.tsx src/components/canvas/__tests__/SelectionOverlay.test.tsx
npm --prefix apps/editor test -- --run src/engine/__tests__/workspaceLayout.test.ts src/engine/__tests__/workspaceViewport.test.ts
npm --prefix apps/editor test -- --run src/engine/__tests__/canvaskitGestures.test.ts src/engine/__tests__/canvaskitConformance.test.ts src/engine/__tests__/gestureConformance.test.ts
```

### Exit Gate

The current behavior is test-anchored before feature changes land.

## Phase P1: Shared Chrome And Focus Model

### Goal

Create a small editor-side model that describes what should be drawn in the
overlay and what should be shown in the inspector/diagnostics focus. This avoids
spreading hover, selection, diagnostics, direct-editability, and slot-bound
logic across `CanvasKitCanvas`, `SelectionOverlay`, and panels.

### Proposed Files

New:

- `apps/editor/src/engine/selectionChrome.ts`

Potentially update:

- `apps/editor/src/engine/canvasSelection.ts`
- `apps/editor/src/engine/sceneQueries.ts`
- `apps/editor/src/components/canvas/SelectionOverlay.tsx`
- `apps/editor/src/components/canvas/__tests__/SelectionOverlay.test.tsx`
- `apps/editor/src/engine/__tests__/selectionChrome.test.ts`

### Proposed Types

Use local naming conventions, but model these concepts explicitly:

```ts
export type SelectedObjectKind =
  | "artboard"
  | "frame"
  | "group"
  | "auto_layout"
  | "text"
  | "image"
  | "shape"
  | "slot_bound"
  | "unknown";

export interface SelectionChromeModel {
  selectedNodeId: NodeId | null;
  selectedObjectKind: SelectedObjectKind | null;
  selectionBox: { box: Box; rotation: number; nodeId: NodeId } | null;
  hoverBox: { box: Box; rotation: number; nodeId: NodeId } | null;
  containerChildren: Box[];
  containerLabel: string | null;
  showHandles: boolean;
  disabledReason: string | null;
  slotKeys: string[];
  diagnosticCounts: {
    errors: number;
    warnings: number;
  };
}
```

Do not overfit this exact shape. The important part is to keep the model
renderer-agnostic and testable.

### Tasks

1. Add a helper that derives selected node object kind:
   - use `node.kind.kind`;
   - if the node is bound to any slot, expose slot-bound status in addition to
     the base node kind;
   - preserve base node controls for slot-bound nodes.

2. Add a helper that derives slot bindings for a node:
   - use existing slot data in `scene.slots`;
   - do not change slot schema;
   - return stable key/id pairs for display.

3. Add a helper that derives direct-manipulation affordance:
   - reuse `isCanvasDirectGeometryEditable`;
   - reuse disabled notice logic from `canvasSelection.ts`;
   - distinguish locked, layout-managed, missing selection, and unsupported
     direct geometry.

4. Add diagnostics count helpers for selected node/artboard:
   - count diagnostics whose subject matches the node;
   - count slot diagnostics for slots bound to the node;
   - count asset diagnostics for assets used by the node;
   - count page diagnostics when no node is selected and active artboard is in
     focus.

5. Keep helpers pure and unit-tested.

### Tests

Add or extend:

- `selectionChrome.test.ts`
  - ordinary text node returns `text`;
  - slot-bound text returns slot keys and still reports base kind;
  - locked node returns disabled reason and no handles;
  - auto-layout managed child returns disabled reason and no handles;
  - selected node diagnostics count includes direct node diagnostic;
  - selected slot-bound node diagnostics count includes bound slot diagnostic.

- `canvasSelection.test.ts`
  - if disabled reason logic is moved or extended.

### Verification

```text
npm --prefix apps/editor test -- --run src/engine/__tests__/selectionChrome.test.ts src/engine/__tests__/canvasSelection.test.ts
```

### Exit Gate

Selection and focus state can be reasoned about in tests without rendering
CanvasKit.

## Phase P2: Overlay Alignment, Hover, And Disabled Handles

### Goal

Make CanvasKit editor chrome feel precise and legible under pan/zoom without
triggering CanvasKit redraws for hover/selection-only changes.

### Files

- `apps/editor/src/components/canvas/CanvasKitCanvas.tsx`
- `apps/editor/src/components/canvas/SelectionOverlay.tsx`
- `apps/editor/src/components/canvas/TextEditOverlay.tsx`
- `apps/editor/src/components/canvas/__tests__/SelectionOverlay.test.tsx`
- `apps/editor/src/engine/canvaskitGestures.ts`
- `apps/editor/src/engine/__tests__/canvaskitGestures.test.ts`
- `apps/editor/src/app/styles.css`

### Tasks

1. Add hover target state in `CanvasKitCanvas`.
   - Use existing `engine.hitTest`.
   - Convert pointer to workspace, artboard-local, and scene coordinates through
     named helpers.
   - Ignore hover during active drag/resize/rotate/marquee/text-edit gestures.
   - Clear hover when outside an artboard or when hit-testing is unavailable.

2. Throttle or coalesce hover hit-testing if needed.
   - Start simple; use pointer move with stable state guards.
   - If tests or browser QA show churn, move to a requestAnimationFrame hover
     scheduler.

3. Extend `SelectionOverlay` to render:
   - hover outline;
   - optional diagnostics accent outline/badge for focused target;
   - optional subtle slot-bound accent when selected;
   - disabled-handle notice anchor near the selection label.

4. Keep overlay props screen/descriptor-space explicit.
   - Avoid passing ambiguous `{x,y}` without naming whether it is descriptor,
     workspace, or screen.

5. Preserve CanvasKit content draw isolation.
   - Hover state must not change the `artboards` descriptor array passed to
     `CanvasKitStage`.
   - Selection overlay state can re-render React/SVG; CanvasKit content should
     only redraw when scene, descriptors, viewport, or active artboard changes.

6. Improve disabled handles.
   - Hidden handles should still show the selected outline.
   - A compact notice or tooltip should explain locked/layout-managed state.
   - Avoid large in-canvas explanatory text that overlaps designs.

7. Keep artboard and canvas colors aligned with product direction.
   - medium dark grey workspace;
   - blank white artboards unless page background says otherwise;
   - visible but restrained active artboard border.

### Tests

Add or extend:

- `SelectionOverlay.test.tsx`
  - renders hover outline separately from selection outline;
  - renders disabled-handle reason without handles;
  - renders slot-bound accent only when slot keys exist;
  - renders diagnostics badge/accent when counts are passed;
  - handle positions still account for zoom and rotation.

- `canvaskitGestures.test.ts`
  - pointer-to-artboard conversion remains stable for pan and zoom.

- `EditorCanvas.test.tsx`
  - CanvasKit and Konva still receive same workspace model.

### Verification

```text
npm --prefix apps/editor test -- --run src/components/canvas/__tests__/SelectionOverlay.test.tsx
npm --prefix apps/editor test -- --run src/engine/__tests__/canvaskitGestures.test.ts src/engine/__tests__/transformerMath.test.ts
npm --prefix apps/editor test -- --run src/components/canvas/__tests__/EditorCanvas.test.tsx
```

### Exit Gate

CanvasKit selection, hover, disabled handles, slot accent, and diagnostics focus
chrome align under pan/zoom and remain independent from content redraw.

## Phase P3: Toolbar And Mode State Machine

### Goal

Make the editor's mode/tool transitions explicit and stable: selecting tools,
opening diagnostics/export/agent, editing text, and switching renderer/view
modes should not reset artboard context.

### Files

New or updated:

- `apps/editor/src/engine/editorModes.ts`
- `apps/editor/src/components/EditorApp.tsx`
- `apps/editor/src/components/canvas/CanvasKitCanvas.tsx`
- `apps/editor/src/components/canvas/CanvasSurface.tsx`
- `apps/editor/src/components/__tests__/EditorApp.test.tsx`
- `apps/editor/src/components/canvas/__tests__/EditorCanvas.test.tsx`
- `apps/editor/src/app/styles.css`

### Proposed State Model

The implementation may keep current state variables, but behavior should follow
this conceptual model:

```ts
type EditorPanelMode = "inspector" | "agent" | "export" | "diagnostics";
type FuturePanelMode = EditorPanelMode | "personalization";
type WorkspaceTool = "select" | "hand";
type WorkspaceViewMode = "canvas" | "export" | "compare";

interface EditorFocusState {
  activeArtboardId: PageId | null;
  selectedNodeId: NodeId | null;
  panelMode: EditorPanelMode;
  workspaceTool: WorkspaceTool;
  workspaceViewMode: WorkspaceViewMode;
  diagnosticsFocus: DiagnosticSubject | null;
}
```

Do not persist this state into `Scene`.

### Tasks

1. Centralize mode labels, aria labels, and ordering.
   - Avoid duplicated mode arrays inside `EditorApp` if they are getting harder
     to test.

2. Make bottom toolbar states testable.
   - Select and hand buttons expose `aria-pressed`.
   - Fit current/all buttons expose active fit target.
   - Diagnostics/export buttons open right-panel modes.
   - Zoom display has stable width to avoid toolbar shifts.

3. Preserve state across transitions:
   - inspector -> agent -> export -> diagnostics -> inspector;
   - canvas -> export preview -> compare -> canvas;
   - select tool -> hand tool -> select tool;
   - text edit start/cancel/commit;
   - renderer flag switch in test harness where feasible.

4. Add a future personalization mode seam without implementing the mode:
   - mode helpers should make adding `"personalization"` mechanical;
   - do not render an inactive feature button unless product wants visible UI.

5. Keep keyboard shortcuts coherent.
   - Escape clears selected node unless text edit overlay owns it.
   - Undo/redo still use operation history.
   - Tool shortcuts can be deferred unless already present.

### Tests

Extend `EditorApp.test.tsx`:

- mode switch preserves active artboard, selected node, viewport, tool, and
  export panel draft state;
- toolbar diagnostics/export buttons set the expected panel mode;
- fit current/all does not mutate scene;
- text edit cancel/commit preserves selected artboard;
- future mode registration test if an `editorModes.ts` helper is added.

Extend `EditorCanvas.test.tsx`:

- renderer switch does not change workspace model input;
- toolbar callback props are passed through both renderers.

### Verification

```text
npm --prefix apps/editor test -- --run src/components/__tests__/EditorApp.test.tsx
npm --prefix apps/editor test -- --run src/components/canvas/__tests__/EditorCanvas.test.tsx
```

### Exit Gate

Panel modes, toolbar tools, viewport, active artboard, selected node, diagnostics
focus, and export panel state survive expected user navigation.

## Phase P4: Inspector Parity And Slot-Bound Selection

### Goal

Make the right inspector explain the selected object class and expose the right
operation-backed controls without losing context for artboards, frames/groups,
text, images, auto-layout containers, layout-managed children, locked nodes, and
slot-bound nodes.

### Files

- `apps/editor/src/components/InspectorPanel.tsx`
- `apps/editor/src/components/SlotInspector.tsx`
- `apps/editor/src/engine/sceneQueries.ts`
- `apps/editor/src/engine/selectionChrome.ts`
- `apps/editor/src/components/__tests__/InspectorPanel.test.tsx`
- `apps/editor/src/engine/__tests__/sceneQueries.test.ts`
- `apps/editor/src/engine/__tests__/selectionChrome.test.ts`
- `apps/editor/src/app/styles.css`

### Tasks

1. Add a selected object summary.
   - page/artboard;
   - text;
   - image;
   - frame/group;
   - auto-layout container;
   - slot-bound node;
   - locked/layout-managed state.

2. For selected artboard/page:
   - keep name, canonical size, unit, safe area, bleed, background/token fill;
   - show page/artboard diagnostics;
   - show export/readiness status if available without duplicating the export
     panel.

3. For selected text:
   - keep content, font, size, weight, align, line height, letter spacing, wrap;
   - show text/render diagnostics;
   - preserve slot-bound state if bound.

4. For selected image:
   - show source asset reference where available;
   - show placement/fit controls that already exist;
   - show asset diagnostics and export limitations;
   - preserve slot-bound state if bound.

5. For frame/group/auto-layout:
   - show transform and size when direct editable;
   - show layout direction/gap/padding/wrap/alignment for auto-layout;
   - show child count and container diagnostics;
   - show why direct handles are disabled when managed by parent layout.

6. For slot-bound nodes:
   - show a compact "Personalized source" or "Slot-bound" section;
   - list existing slot keys bound to the selected node;
   - link to existing `SlotInspector` details where available;
   - do not replace ordinary geometry/style/layout controls;
   - do not make the right panel a slot browser.

7. Focused diagnostics:
   - keep selected node/artboard diagnostics near relevant controls;
   - include diagnostics for slots bound to the selected node;
   - include asset diagnostics for image/source asset selections;
   - subject buttons should route through existing `selectDiagnosticSubject`.

### Tests

Extend `InspectorPanel.test.tsx`:

- selected artboard shows canonical page controls and page diagnostics;
- selected text shows text controls and selected diagnostics;
- selected image shows asset/source context and selected diagnostics;
- selected auto-layout container shows layout controls;
- layout-managed child has disabled geometry controls and reason;
- locked node has disabled destructive/direct-edit controls and reason;
- slot-bound selected node shows slot key while retaining normal controls;
- slot diagnostic on selected slot-bound node appears in focused diagnostics.

Extend `sceneQueries.test.ts`:

- helper returns slot bindings for selected node;
- helper returns no bindings for ordinary node;
- multi-bound slots return stable ordering.

### Verification

```text
npm --prefix apps/editor test -- --run src/components/__tests__/InspectorPanel.test.tsx
npm --prefix apps/editor test -- --run src/engine/__tests__/sceneQueries.test.ts src/engine/__tests__/selectionChrome.test.ts
```

### Exit Gate

Selected object inspection is coherent for the branch's object classes, and
slot-bound status is visible without turning the sidebar into the primary slot
authoring workflow.

## Phase P5: Diagnostics Focus And Artboard Readiness

### Goal

Make diagnostics actionable in the selected-artboard workflow. A user should
understand which artboard/object is affected and be able to focus it without
losing diagnostics context.

### Files

- `apps/editor/src/components/ValidationPanel.tsx`
- `apps/editor/src/components/EditorApp.tsx`
- `apps/editor/src/engine/workspaceLayout.ts`
- `apps/editor/src/engine/selectionChrome.ts`
- `apps/editor/src/components/PageRail.tsx`
- `apps/editor/src/components/canvas/SelectionOverlay.tsx`
- `apps/editor/src/components/__tests__/EditorApp.test.tsx`
- `apps/editor/src/engine/__tests__/workspaceLayout.test.ts`

### Tasks

1. Normalize diagnostic status levels for artboard badges.
   - `error`: blocking diagnostics;
   - `warning`: warnings and warning-only export/readiness issues;
   - `ready`: no current diagnostics;
   - `unknown`: no validation/export check has run, if this can be represented
     without confusing existing status dots.

2. Keep diagnostic subject routing stable:
   - page subject activates artboard;
   - node subject activates owning artboard and selects node;
   - slot subject activates first bound node and owning artboard;
   - asset subject activates first node using asset and owning artboard;
   - document subject stays document-level.

3. Preserve Diagnostics mode after subject navigation.
   - The user should be able to click diagnostic subjects and stay in the
     diagnostics surface.
   - Inspector can still show focused diagnostics when opened separately.

4. Connect chrome to diagnostics focus.
   - If a selected node/artboard has focused errors, show subtle red/orange
     accent in overlay or label.
   - Do not make diagnostic badges obscure design content.

5. Include slot-related diagnostics in focus rules.
   - Existing `DiagnosticSubject.kind === "slot"` should count as focused when
     selected node is bound to that slot.
   - Do not invent new diagnostic subject schema in this branch unless strictly
     needed.

### Tests

Extend `EditorApp.test.tsx`:

- page diagnostic subject activates page and keeps diagnostics panel active;
- node diagnostic subject activates owning artboard and selects node;
- slot diagnostic subject activates first bound node and keeps diagnostics panel
  active;
- asset diagnostic subject activates first using node and keeps diagnostics
  panel active;
- focused diagnostics exclude unrelated diagnostics from focused section.

Extend `workspaceLayout.test.ts`:

- artboard diagnostics summary includes page, node, slot, and asset diagnostics
  mapped to that artboard;
- unmapped document diagnostics do not pollute artboard badge counts.

Extend `SelectionOverlay.test.tsx`:

- diagnostics accent renders when counts are passed.

### Verification

```text
npm --prefix apps/editor test -- --run src/components/__tests__/EditorApp.test.tsx
npm --prefix apps/editor test -- --run src/engine/__tests__/workspaceLayout.test.ts
npm --prefix apps/editor test -- --run src/components/canvas/__tests__/SelectionOverlay.test.tsx
```

### Exit Gate

Diagnostics are visible, focused, and navigable by artboard/node/slot/asset
without clearing context or leaving Diagnostics mode unexpectedly.

## Phase P6: Export Readiness And Preview Affordances

### Goal

Make selected-artboard export status explicit before download and keep export
scope/profile/preview state coherent across the editor.

### Files

- `apps/editor/src/components/ExportPanel.tsx`
- `apps/editor/src/components/ExportPreviewSurface.tsx`
- `apps/editor/src/components/EditorApp.tsx`
- `apps/editor/src/engine/exportPreviewApproval.ts`
- `apps/editor/src/engine/exportParity.ts`
- `apps/editor/src/engine/exportRunner.ts`
- `apps/editor/src/components/__tests__/EditorApp.test.tsx`
- `apps/editor/src/components/__tests__/ExportPreviewSurface.test.tsx`
- `apps/editor/src/engine/__tests__/exportPreviewApproval.test.ts`
- `apps/editor/src/engine/__tests__/exportRunner.test.ts`

### Tasks

1. Audit selected-artboard/all-artboards copy.
   - Use "selected artboard" in user-facing controls.
   - Keep internal `pageIds` names where API contracts require them.

2. Strengthen readiness summary.
   - Include active artboard name.
   - Include profile name.
   - Distinguish:
     - no artifact;
     - export failed;
     - parity mismatch;
     - blocking diagnostics;
     - warning-only review state;
     - ready.

3. Preserve export panel state.
   - selected profile;
   - selected/all scope;
   - draft profile edits;
   - latest export result;
   - active artboard context after diagnostic navigation.

4. Stale preview handling.
   - If cheap and local, mark preview stale when scene revision, active artboard,
     selected profile, or export scope changes after export.
   - If full stale tracking is too broad, explicitly defer it and keep readiness
     based on latest result plus current diagnostics.

5. Sidecar/artifact confirmation.
   - Artifact rows should show format, artboard ID, profile, dimensions, node
     count, slot count, and slot keys where available.
   - Selected-artboard preview should never display another artboard's artifact
     as the active preview.

6. Slot readiness hook.
   - Do not implement full slot validation here.
   - Ensure existing sidecar slot counts/keys and slot diagnostics can appear in
     export/readiness surfaces.

### Tests

Extend `ExportPreviewSurface.test.tsx`:

- selected active artboard artifact is shown;
- another page's artifact is not shown for active artboard;
- warning-only diagnostics produce review state;
- error diagnostics block approval;
- sidecar slot keys are visible.

Extend `exportPreviewApproval.test.ts`:

- no artifact fails closed;
- failed export fails closed;
- parity mismatch fails closed;
- error diagnostics fail closed;
- warning diagnostics produce review state;
- clean artifact produces ready state.

Extend `EditorApp.test.tsx`:

- selected-artboard export sends active page ID;
- all-artboards export sends all page IDs;
- export panel state survives mode switches and diagnostics navigation;
- export preview/compare view does not reset viewport.

### Verification

```text
npm --prefix apps/editor test -- --run src/components/__tests__/ExportPreviewSurface.test.tsx
npm --prefix apps/editor test -- --run src/engine/__tests__/exportPreviewApproval.test.ts src/engine/__tests__/exportRunner.test.ts
npm --prefix apps/editor test -- --run src/components/__tests__/EditorApp.test.tsx
```

### Exit Gate

A user can validate, preview, understand readiness, and export the selected
artboard without guessing the active scope or relying on raw diagnostics.

## Phase P7: Personalization Hooks For Future X-Ray

### Goal

Ensure this branch does not block the future personalization review/X-ray
branch, without pulling X-ray itself into scope.

### Files

- `docs/slot-personalization-binding-architecture.md`
- `apps/editor/src/engine/selectionChrome.ts`
- `apps/editor/src/engine/sceneQueries.ts`
- `apps/editor/src/components/canvas/SelectionOverlay.tsx`
- `apps/editor/src/components/InspectorPanel.tsx`
- `apps/editor/src/components/ValidationPanel.tsx`
- `apps/editor/src/components/ExportPreviewSurface.tsx`
- `apps/editor/src/components/__tests__/InspectorPanel.test.tsx`
- `apps/editor/src/components/canvas/__tests__/SelectionOverlay.test.tsx`
- `apps/editor/src/engine/__tests__/selectionChrome.test.ts`
- `apps/editor/src/engine/__tests__/sceneQueries.test.ts`

### Tasks

1. Keep the slot architecture doc as product direction, not implementation
   scope creep.

2. Add helper-level support for slot-bound selected objects:
   - selected node -> bound slots;
   - selected node -> slot keys for overlay/inspector;
   - diagnostic slot subject -> bound node/artboard focus.

3. Add overlay seams:
   - a subtle selected slot-bound accent;
   - optional slot label data shape;
   - no persistent chips in normal mode;
   - no X-ray dimming.

4. Add inspector seams:
   - selected slot-bound node summary;
   - existing slot details link/section;
   - no all-slot browser as primary workflow.

5. Add mode seams:
   - code organization allows a future `personalization` mode;
   - no visible X-ray mode until the future branch.

6. Add export/diagnostics seams:
   - slot diagnostics can appear in readiness/focused diagnostics;
   - sidecar slot keys remain visible.

### Tests

- selected slot-bound node renders slot-bound summary;
- selected slot-bound node still exposes ordinary node controls;
- selection overlay can receive slot keys without layout drift;
- slot diagnostic navigation focuses first bound node;
- export preview displays sidecar slot keys.

### Verification

```text
npm --prefix apps/editor test -- --run src/engine/__tests__/selectionChrome.test.ts src/engine/__tests__/sceneQueries.test.ts
npm --prefix apps/editor test -- --run src/components/__tests__/InspectorPanel.test.tsx src/components/canvas/__tests__/SelectionOverlay.test.tsx
npm --prefix apps/editor test -- --run src/components/__tests__/EditorApp.test.tsx src/components/__tests__/ExportPreviewSurface.test.tsx
```

### Exit Gate

The future `editor/personalization-xray-v0` branch can add X-ray, selected-slot
inspector, and on-canvas personalization toggles without inventing a parallel
selection, overlay, panel, diagnostics, or export-readiness model.

## Phase P8: Renderer Parity And Final QA

### Goal

Prove polish did not break CanvasKit gesture behavior, Konva fallback, export
readiness, or the editor's canonical operation contract.

### Required Non-Browser Verification

Run targeted first:

```text
npm --prefix apps/editor test -- --run src/components/__tests__/EditorApp.test.tsx
npm --prefix apps/editor test -- --run src/components/canvas/__tests__/EditorCanvas.test.tsx src/components/canvas/__tests__/SelectionOverlay.test.tsx
npm --prefix apps/editor test -- --run src/components/__tests__/InspectorPanel.test.tsx src/components/__tests__/ExportPreviewSurface.test.tsx
npm --prefix apps/editor test -- --run src/engine/__tests__/workspaceLayout.test.ts src/engine/__tests__/workspaceViewport.test.ts
npm --prefix apps/editor test -- --run src/engine/__tests__/canvaskitGestures.test.ts src/engine/__tests__/canvaskitConformance.test.ts src/engine/__tests__/gestureConformance.test.ts
npm --prefix apps/editor test -- --run src/engine/__tests__/exportRunner.test.ts src/engine/__tests__/exportPreviewApproval.test.ts
```

Then run broader:

```text
npm --prefix apps/editor test -- --run --testTimeout 20000
npm --prefix apps/editor run lint
git diff --check
```

Before merge or integration, if code changes touch Rust/core/API contracts,
also run:

```text
cargo test --workspace
/Users/aryankeshri/Documents/brilliant-design/.venv/bin/python -m pytest apps/api/tests/test_api.py -q
/Users/aryankeshri/Documents/brilliant-design/.venv/bin/python -m pytest apps/api/tests/test_phase_g_conformance.py -q
```

Use the narrower API loop first if only API behavior is in question:

```text
/Users/aryankeshri/Documents/brilliant-design/.venv/bin/python -m pytest apps/api/tests/test_api.py -q
/Users/aryankeshri/Documents/brilliant-design/.venv/bin/python -m pytest apps/api/tests/test_phase_g_conformance.py -q
```

### Browser Verification

Do not run browser-rendered editor smoke unless the user explicitly schedules
the browser-plugin QA session for this branch.

When scheduled, cover:

- default renderer nonblank editor shell;
- CanvasKit renderer nonblank editor shell;
- medium dark grey workspace;
- blank white bounded artboards;
- left artboard list with size metadata plus layer hierarchy tree below;
- selection hover/handles under pan and zoom;
- disabled handles for locked/layout-managed nodes;
- selected slot-bound node indicator if implemented;
- diagnostics subject navigation;
- selected-artboard export request sends only active page ID;
- export preview and compare preserve viewport;
- narrow viewport sanity;
- no stable console errors.

### Exit Gate

CanvasKit gesture conformance remains green, editor tests pass, lint passes, and
the implementation still respects the canonical `Scene`/`Operation` boundary.

## Recommended Commit Order

Use clear checkpoint messages:

1. `Add CanvasKit polish implementation plan`
2. `Add selection chrome model tests`
3. `Polish CanvasKit hover and selection chrome`
4. `Harden editor toolbar mode state`
5. `Improve inspector focused selection states`
6. `Polish selected-artboard export readiness`
7. `Prepare slot-bound selection hooks`
8. `Finalize CanvasKit polish verification docs`

Keep unrelated documents and user edits out of these commits unless the user
explicitly asks to include them.

## Implementation Checklist

### Planning

- [ ] Confirm current dirty worktree and avoid staging unrelated user changes.
- [ ] Read the spec and slot architecture doc.
- [ ] Read branch/dependency memory files.
- [ ] Read relevant reference docs.
- [ ] Identify tests that already cover baseline behavior.

### Selection And Overlay

- [ ] Add pure selection/chrome model helper.
- [ ] Add selected object kind derivation.
- [ ] Add slot-bound selected node derivation.
- [ ] Add diagnostic count derivation for selected node/artboard.
- [ ] Add hover target state.
- [ ] Add hover outline.
- [ ] Add disabled-handle reason display.
- [ ] Add subtle slot-bound selected accent.
- [ ] Add diagnostics accent/badge.
- [ ] Verify no CanvasKit redraw on hover-only changes where testable.

### Toolbar And Modes

- [ ] Centralize mode metadata if useful.
- [ ] Add stable toolbar active/disabled/pressed states.
- [ ] Preserve context across panel modes.
- [ ] Preserve context across canvas/export/compare views.
- [ ] Preserve context across text edit commit/cancel.
- [ ] Keep future personalization mode mechanically addable.

### Inspector

- [ ] Audit artboard inspector.
- [ ] Audit frame/group inspector.
- [ ] Audit text inspector.
- [ ] Audit image inspector.
- [ ] Audit auto-layout inspector.
- [ ] Audit locked/layout-managed disabled states.
- [ ] Add slot-bound selected node summary.
- [ ] Keep ordinary controls available for slot-bound nodes.
- [ ] Show focused diagnostics near relevant controls.

### Diagnostics And Export

- [ ] Normalize artboard badge status.
- [ ] Preserve Diagnostics mode on subject focus.
- [ ] Ensure page/node/slot/asset subject routing works.
- [ ] Surface selected-artboard readiness.
- [ ] Preserve export panel state across navigation.
- [ ] Confirm selected-artboard export page IDs.
- [ ] Confirm sidecar slot keys remain visible.
- [ ] Decide and document stale preview handling.

### Final

- [ ] Run targeted editor tests.
- [ ] Run full editor suite with extended timeout.
- [ ] Run lint.
- [ ] Run `git diff --check`.
- [ ] Run Rust/API tests if code touched shared contracts.
- [ ] Update branch memory with durable decisions and verification.
- [ ] Commit with clear messages.
- [ ] Do not push unless requested.

## Completion Audit

Before declaring the branch complete, verify every spec acceptance item:

| Spec Requirement | Evidence Needed |
|---|---|
| Dark side panels and medium dark grey workspace retained | Component tests plus browser QA when scheduled |
| Blank white bounded artboards retained | Component tests plus browser QA when scheduled |
| Left rail has artboard list/sizes plus layer tree | `PageRail`/`LayerPanel` tests or `EditorApp` tests |
| Active artboard preserved across modes | `EditorApp.test.tsx` |
| Selected node preserved across modes | `EditorApp.test.tsx` |
| Workspace viewport preserved across modes | `EditorApp.test.tsx` |
| CanvasKit chrome aligns under pan/zoom | `SelectionOverlay`/gesture tests; browser QA when scheduled |
| Locked/layout-managed direct handles explain disabled state | `SelectionOverlay` and `InspectorPanel` tests |
| Inspector parity for required object classes | `InspectorPanel.test.tsx` |
| Slot-bound node state recognized | `selectionChrome`, `sceneQueries`, `InspectorPanel` tests |
| Export readiness visible | `ExportPreviewSurface` and `EditorApp` tests |
| Selected-artboard export maps to active page ID | `EditorApp.test.tsx` / `exportRunner.test.ts` |
| Diagnostics focus relevant artboard/node/slot/asset | `EditorApp`, `ValidationPanel`, `workspaceLayout` tests |
| CanvasKit/Konva consume same workspace model | `EditorCanvas.test.tsx` |
| CanvasKit gesture conformance remains green | `canvaskitConformance.test.ts` |
| No second scene model or raw scene mutation | Code review and operation-builder tests |

Only mark the branch complete when current evidence proves each requirement or
the user explicitly defers a verification class such as browser-plugin QA.
