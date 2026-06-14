# Editor Infinite Workspace V0 Implementation Plan

Date: 2026-06-14
Branch: `editor/infinite-workspace-v0`
Spec: `docs/editor-infinite-workspace-v0-spec.md`
Primary source plan: `docs/artboard-workspace-geometry-plan.md`

## Implementation Goal

Implement Slice 2 and Slice 3 from the artboard workspace geometry plan:

- Slice 2: dark editor shell and product chrome.
- Slice 3: medium dark grey infinite workspace with bounded artboard/page frames.

The implementation should keep the existing scene and operation model intact. It should introduce a derived editor workspace model that uses canonical artboard/page geometry from Branch 1, arranges pages as artboards in workspace coordinates, and feeds both Konva and CanvasKit adapters through the same viewport and coordinate helpers.

## Current Starting Point

Relevant current files:

- `apps/editor/src/components/EditorApp.tsx`
  - Owns scene state, active page, selected node, diagnostics, export, agent state, and the current three-column editor layout.
- `apps/editor/src/components/canvas/EditorCanvas.tsx`
  - Switches between CanvasKit and Konva via the existing feature flag.
- `apps/editor/src/components/canvas/CanvasSurface.tsx`
  - Konva renderer. It currently renders one active page centered in a page preview shell with local zoom and pan.
- `apps/editor/src/components/canvas/CanvasKitCanvas.tsx`
  - CanvasKit renderer. It currently fits one active page and has deferred pan/zoom parity.
- `apps/editor/src/engine/canvasViewport.ts`
  - Single-page fit, center, zoom, and pan helpers.
- `apps/editor/src/components/PageRail.tsx`
  - Existing page list and page actions.
- `apps/editor/src/components/LayerPanel.tsx`
  - Existing active-page layer tree.
- `apps/editor/src/components/ExportPanel.tsx`
  - Existing active/all page export scope UI.
- `apps/editor/src/engine/exportRunner.ts`
  - Existing API adapter that passes `pageIds`.
- `apps/editor/src/app/styles.css`
  - Current light shell and preview styling.

## Phase IW0: Baseline And Guardrails

Purpose: make the branch measurable before changing the renderer.

Work:

- Confirm the editor worktree is based on `engine/canonical-artboard-geometry-v0`.
- Identify the canonical page/artboard descriptor helper from Branch 1 and make it the only source of layout width/height.
- Add or update tests that document current export scope behavior before UI copy changes.
- Add a short fixture with multiple pages of different sizes if one does not already exist.
- Keep browser rendered smoke deferred for the Codex Browser plugin session.

Verification:

- `npm --prefix apps/editor test -- --run apps/editor/src/engine/exportRunner.test.ts`
- `npm --prefix apps/editor test -- --run apps/editor/src/engine/canvasViewport.test.ts`
- `git diff --check`

Exit gate:

- Existing editor tests still pass before the workspace refactor begins.
- The branch has a known fixture or test scene for differently sized pages.

## Phase IW1: Workspace View Model And Geometry Helpers

Purpose: establish one workspace coordinate contract before touching Konva or CanvasKit.

Add:

- `apps/editor/src/engine/workspaceLayout.ts`
- `apps/editor/src/engine/workspaceLayout.test.ts`
- `apps/editor/src/engine/workspaceViewport.ts`
- `apps/editor/src/engine/workspaceViewport.test.ts`

Core types:

```ts
export interface WorkspaceArtboard {
  pageId: string;
  name: string;
  label: string;
  layoutWidth: number;
  layoutHeight: number;
  workspaceRect: Rect;
  isActive: boolean;
  diagnosticsSummary: DiagnosticsSummary;
}

export interface WorkspaceModel {
  artboards: WorkspaceArtboard[];
  bounds: Rect;
  activeArtboard?: WorkspaceArtboard;
}

export interface WorkspaceViewport {
  zoom: number;
  pan: Point;
}
```

Implementation tasks:

- Derive one `WorkspaceArtboard` per scene page.
- Use canonical layout dimensions from the Branch 1 page descriptor.
- Synthesize deterministic artboard placement from page order.
- Compute `bounds` for all artboards plus label/toolbar padding.
- Implement `fitWorkspaceRectToViewport`.
- Implement `screenToWorkspace`, `workspaceToScreen`, `workspaceToArtboardLocal`, and `artboardLocalToWorkspace`.
- Keep all helpers renderer-agnostic.

Placement V0:

- Start at `{ x: 0, y: 0 }`.
- Use a fixed workspace gap large enough for labels and visual separation.
- Place artboards left-to-right.
- Wrap to a new row when cumulative row width exceeds a configurable target.
- Row height is the max artboard height in the row.
- Return stable results for identical page order and dimensions.

Tests:

- Artboard layout is stable for repeated inputs.
- Differently sized artboards have non-overlapping rects.
- Bounds include all artboards.
- Fit current returns a zoom/pan that keeps one artboard visible.
- Fit all returns a zoom/pan that keeps all artboards visible.
- Transform round trips preserve points within tolerance.
- Physical print metadata never changes layout dimensions.

Exit gate:

- Renderers can consume a single `WorkspaceModel` and `WorkspaceViewport` without needing page-specific origin math.

## Phase IW2: Editor State And Product Shell

Purpose: create the dark shell and central workspace structure without changing drawing behavior more than necessary.

Modify:

- `apps/editor/src/components/EditorApp.tsx`
- `apps/editor/src/app/styles.css`

Add or extract:

- `apps/editor/src/components/shell/EditorShell.tsx`
- `apps/editor/src/components/shell/TopContextBar.tsx`
- `apps/editor/src/components/shell/LeftWorkspacePanel.tsx`
- `apps/editor/src/components/shell/RightWorkspacePanel.tsx`
- `apps/editor/src/components/workspace/WorkspaceToolbar.tsx`

State additions:

```ts
type EditorMode = "edit" | "agent" | "export" | "diagnostics";
type WorkspaceTool = "select" | "hand";
type FitTarget = "current" | "all";
```

Implementation tasks:

- Keep `activePageId` as the persisted state name for now, but expose it in UI/component props as `activeArtboardId` where appropriate.
- Add `editorMode` state that chooses the right panel surface.
- Add `workspaceTool` state for select vs hand.
- Move current top preview controls into the new compact context bar or bottom toolbar.
- Restyle left and right panels as dark chrome.
- Restyle central area as a medium dark grey infinite workspace.
- Keep existing panels mounted or state-preserving where practical.
- Do not add browser-only dependencies.

Tests:

- Rendering the editor shell shows left, center, right, top context, and bottom toolbar regions.
- Mode switch changes the visible right-panel surface.
- Switching modes does not clear active artboard or selected node.

Exit gate:

- The editor visually has the intended shell architecture even if the renderer is still in transition.

## Phase IW3: Konva Multi-Artboard Workspace

Purpose: make the default renderer support the new workspace model first.

Modify:

- `apps/editor/src/components/canvas/EditorCanvas.tsx`
- `apps/editor/src/components/canvas/CanvasSurface.tsx`
- `apps/editor/src/components/canvas/KonvaNodeRenderer.tsx` if needed.
- `apps/editor/src/engine/canvasViewport.ts` only if old helpers can be safely reused or deprecated.

Implementation tasks:

- Pass `WorkspaceModel`, `WorkspaceViewport`, active artboard, and workspace tool into the Konva surface.
- Render all artboards in the workspace model.
- Move each page's children into an artboard group translated by `workspaceRect.x/y`.
- Apply clipping to each artboard group.
- Render artboard background, border, shadow, safe area, bleed, labels, and diagnostics badges.
- Convert node hit testing and drag positions through workspace -> artboard-local coordinates.
- Keep scene operations identical to current single-page editing operations.
- Add empty-workspace click behavior.
- Add active-artboard background click behavior.

Tests:

- Multi-artboard scene renders one group per page.
- Dragging a node in one artboard emits artboard-local coordinates.
- Clicking a node activates its artboard and selects the node.
- Clicking artboard background activates the artboard without selecting a node.
- Clipping is enabled on artboard groups.

Exit gate:

- Konva path can inspect and edit multiple differently sized artboards without changing scene dimensions.

## Phase IW4: CanvasKit Workspace Parity

Purpose: bring CanvasKit to the same workspace contract instead of leaving it as a fit-to-active-page renderer.

Modify:

- `apps/editor/src/components/canvas/CanvasKitCanvas.tsx`
- `apps/editor/src/components/canvaskit/CanvasKitStage.tsx`
- `apps/editor/src/components/canvaskit/SelectionOverlay.tsx`
- `apps/editor/src/components/canvaskit/TextEditOverlay.tsx`
- `apps/editor/src/components/canvaskit/canvaskitDrawing.ts` if drawing helpers need clip scopes.

Implementation tasks:

- Feed CanvasKit the same `WorkspaceModel` and `WorkspaceViewport`.
- Draw each artboard at its workspace rect.
- Clip each artboard before drawing children.
- Align DOM/SVG overlays with workspace pan/zoom.
- Convert pointer events using shared workspace transform helpers.
- Preserve existing CanvasKit gesture conformance expectations.
- Keep the feature flag behavior unchanged.

Tests:

- Existing CanvasKit conformance tests still pass.
- CanvasKit and Konva use the same workspace layout helper in tests.
- CanvasKit overlay positions match expected transformed workspace/artboard-local rects.
- CanvasKit path does not call single-page fit helpers for normal workspace rendering.

Exit gate:

- Toggling the feature flag does not change artboard placement, active selection semantics, clipping rules, or emitted operations.

## Phase IW5: Pan, Zoom, Fit Current, Fit All

Purpose: make the workspace usable as an infinite canvas rather than a static multi-page preview.

Modify:

- `apps/editor/src/components/workspace/WorkspaceToolbar.tsx`
- `apps/editor/src/components/canvas/CanvasSurface.tsx`
- `apps/editor/src/components/canvas/CanvasKitCanvas.tsx`
- `apps/editor/src/engine/workspaceViewport.ts`

Implementation tasks:

- Store viewport state at the shared `EditorApp` or workspace shell level, not inside only one renderer.
- Implement wheel/pinch zoom around pointer when possible.
- Implement hand-tool drag pan.
- Implement select-tool panning modifier if current conventions allow it.
- Implement zoom in/out commands.
- Implement fit current artboard.
- Implement fit all artboards.
- Clamp only to avoid losing the document completely; do not make the workspace feel page-bound.
- Keep viewport state across renderer flag toggles and right-panel mode switches.

Tests:

- Fit current uses active artboard bounds.
- Fit all uses workspace model bounds.
- Zoom around a point preserves the workspace point under the pointer.
- Tool changes do not emit scene operations.
- Pan/zoom changes do not mutate scene or page geometry.

Exit gate:

- Users can comfortably navigate multiple artboards in both renderer modes.

## Phase IW6: Artboard-Aware Panels, Export, And Diagnostics

Purpose: wire the shell into actual product workflows.

Modify:

- `apps/editor/src/components/PageRail.tsx`
- `apps/editor/src/components/LayerPanel.tsx`
- `apps/editor/src/components/ExportPanel.tsx`
- `apps/editor/src/components/ValidationPanel.tsx`
- `apps/editor/src/components/PreflightPanel.tsx` if present.
- `apps/editor/src/engine/exportRunner.ts` only if UI state needs a clearer adapter.

Implementation tasks:

- Rename UI copy from page to artboard where this branch owns the surface.
- Show artboard size and diagnostics status in the left panel.
- Scope layer tree to active artboard.
- Add diagnostic click behavior: activate artboard, select node when possible, and open diagnostics mode.
- Add export scope copy: selected artboard and all artboards.
- Ensure selected-artboard export maps to `pageIds: [activeArtboardId]`.
- Ensure all-artboards export maps to all scene page ids.
- Keep API payloads backward compatible.

Tests:

- Export selected artboard sends only the active page id.
- Export all artboards sends every page id.
- Diagnostics selection activates the expected artboard.
- Left-panel artboard selection updates active artboard without changing scene geometry.

Exit gate:

- The editor can inspect, diagnose, and export an artboard without forcing a global scene-size mental model.

## Phase IW7: Visual Polish, Accessibility, And Responsive Safety

Purpose: make the shell direction credible before merge.

Modify:

- `apps/editor/src/app/styles.css`
- Component-specific class names introduced in previous phases.

Implementation tasks:

- Ensure dark side panels use restrained neutral colors and readable contrast.
- Ensure central workspace remains medium dark grey and visually distinct from artboard/page frames.
- Ensure each page maps to exactly one visible drawable frame in V0.
- Keep artboard labels compact and non-overlapping.
- Ensure bottom toolbar has stable dimensions and does not shift when labels/status change.
- Add accessible labels and tooltips for icon buttons.
- Ensure text does not overflow compact toolbar buttons or side-panel rows.
- Add collapsed or overflow behavior for narrow widths if the existing app shell supports it.

Tests:

- Component tests for important labels and accessible names.
- CSS review for accidental one-note palette or oversized marketing-style elements.
- `git diff --check`.

Exit gate:

- The UI direction matches the target shell: dark side panels, medium dark grey workspace, bounded artboard/page frames, compact labels, floating toolbar.

## Phase IW8: Final Verification And Handoff

Purpose: leave a clear branch that another parallel workstream can build on.

Verification commands:

```bash
npm --prefix apps/editor test -- --run
npm --prefix apps/editor run lint
git diff --check
```

Targeted tests to include or update:

- `apps/editor/src/engine/workspaceLayout.test.ts`
- `apps/editor/src/engine/workspaceViewport.test.ts`
- `apps/editor/src/engine/exportRunner.test.ts`
- `apps/editor/src/components/canvas/canvaskitConformance.test.ts`
- `apps/editor/src/components/canvas/gestureConformance.test.ts`
- Editor shell component tests where the existing test setup supports them.

Deferred verification:

- Browser-rendered smoke.
- Screenshot comparison.
- Canvas pixel checks.

These are intentionally deferred until the Codex Browser plugin session requested by the user. The branch should still be structured so that browser smoke can check:

- Multiple artboards visible at once.
- Fit current.
- Fit all.
- Renderer flag parity.
- Artboard clipping.
- Export selected artboard UX.

## Migration Strategy

This branch should avoid a big-bang rewrite:

1. Land renderer-agnostic workspace helpers.
2. Introduce shell state and layout while the current renderer still works.
3. Convert Konva to multi-artboard.
4. Convert CanvasKit to the same contract.
5. Wire export and diagnostics to artboard language.
6. Polish styling and tests.

If CanvasKit parity takes longer than expected, keep the shared model and helper tests complete and isolate the remaining CanvasKit gap behind explicit failing/skipped tests or a documented TODO. Do not let CanvasKit invent a parallel layout path.

## Risks And Mitigations

Risk: Branch 2 accidentally reintroduces page-unit scaling bugs.

Mitigation: all artboard dimensions come from the Branch 1 canonical descriptor, and tests assert print metadata does not affect workspace layout.

Risk: CanvasKit and Konva drift.

Mitigation: both paths consume the same `WorkspaceModel`, viewport helpers, and coordinate transforms. Gesture conformance tests should remain renderer-agnostic.

Risk: the shell rewrite breaks existing panel state.

Mitigation: preserve existing component instances where practical, move panels behind mode surfaces gradually, and test mode switches.

Risk: workspace placement becomes a hidden document model.

Mitigation: do not persist workspace positions in V0. Treat layout as deterministic derived view state.

Risk: visual work consumes the branch.

Mitigation: implement shell structure and stable controls first. Polish only enough to satisfy the stated dark-shell/medium-dark-grey-workspace direction.

## Branch Completion Checklist

- [x] `WorkspaceModel` derives artboards from scene pages.
- [x] Workspace placement is deterministic and tested.
- [x] Workspace viewport transforms are shared and tested.
- [x] Dark left panel contains artboards and active-artboard layers.
- [x] Dark right panel supports inspector, agent, export, and diagnostics modes.
- [x] Compact top context bar shows active artboard and mode.
- [x] Floating bottom toolbar supports select, pan, zoom, fit current, and fit all.
- [x] Konva renders multiple clipped artboards.
- [x] CanvasKit renders multiple clipped artboards with matching transforms.
- [x] Active artboard selection works from panel and workspace.
- [x] Node selection activates its owning artboard.
- [x] Export selected artboard sends the correct page id.
- [x] Diagnostics visibly map to artboards.
- [x] Viewport changes do not mutate scene geometry or emit scene operations.
- [x] Tests and lint pass, except browser smoke explicitly deferred to the Browser plugin session.

Completion checkpoint, 2026-06-14:

- `npm --prefix apps/editor test -- --run src/components/__tests__/EditorApp.test.tsx src/components/canvas/__tests__/EditorCanvas.test.tsx src/engine/__tests__/workspaceLayout.test.ts src/engine/__tests__/workspaceViewport.test.ts src/engine/__tests__/canvaskitGestures.test.ts src/engine/__tests__/canvaskitConformance.test.ts src/engine/__tests__/gestureConformance.test.ts src/engine/__tests__/exportRunner.test.ts` passed 8 files and 71 tests.
- `npm --prefix apps/editor run lint` passed.
- `git diff --check` passed.
- `npm --prefix apps/editor test -- --run` passed 43 files and 312 tests.
- Browser-rendered smoke, screenshot comparison, and canvas-pixel checks remain deferred to the separate Codex Browser plugin session requested by the user.
