# Editor Infinite Workspace V0 Spec

Date: 2026-06-14
Branch: `editor/infinite-workspace-v0`
Base dependency: `engine/canonical-artboard-geometry-v0`

## Purpose

This branch implements Branch 2 from `docs/artboard-workspace-geometry-plan.md`: Slice 2, the editor product shell, and Slice 3, the infinite canvas workspace. It turns the editor from a single-page preview surface into a Figma/Brilliant-inspired workspace where bounded artboard/page frames sit on a medium dark grey infinite canvas inside a dark production editor shell.

The important contract is that Branch 2 consumes canonical artboard geometry. It must not invent another coordinate system, silently repair page units, or persist workspace placement into the scene model. The scene remains the source of truth for pages, nodes, canonical layout dimensions, operations, and export intent. The editor workspace is an adapter that lets users inspect, select, pan, zoom, diagnose, and export artboards without mutating scene geometry.

## Source Alignment

This spec is constrained by these source documents:

- `docs/artboard-workspace-geometry-plan.md`
- `.codex/memory/workstreams/engine-canonical-artboard-geometry-v0.md`
- `.codex/memory/workstreams/editor-infinite-workspace-v0.md`
- `design/reference_docs/ABM-Design-Engine-Temporary-Spec.md`
- `design/reference_docs/Brilliant-Reverse-Engineering-Report.md`
- `design/reference_docs/Brilliant-vs-Lumen-Product-Gap-Analysis.md`

The durable Brilliant/Figma lesson is not the visual chrome alone. It is that the design artifact is a bounded frame/artboard inside a larger workspace, children resolve in the artifact's local coordinate space, and export targets the selected artifact rather than the whole infinite workspace.

## Scope

Branch 2 owns:

- Dark left pages/artboards/layers panel.
- Dark right inspector, agent, export, and diagnostics panel surface.
- Compact top artboard label and editor mode switch.
- Floating bottom workspace toolbar.
- Medium dark grey infinite workspace background.
- Pan and zoom over the workspace.
- Multiple artboard frames visible at once.
- Artboard labels and active-artboard selection.
- Artboard clipping in both renderer paths.
- Fit current artboard and fit all artboards.
- Export-selected-artboard UX.
- CanvasKit and Konva parity under the existing feature flag.

Branch 2 does not own:

- Canonical page/artboard geometry DTO design. That belongs to Branch 1.
- Changing persisted scene coordinates from page-local to any other model.
- Persisting artboard workspace positions into the scene.
- Loose top-level workspace objects outside artboards.
- Multiple frames per page. One page maps to one drawable frame/artboard in V0.
- Agent generation recipes for artboard-as-frame output.
- Layout-cluster repair routing.
- Whole-scene regeneration, repair permissions, or prompt evaluator work.
- Full CanvasKit production polish beyond parity needed for this shell.

## Product Principles

1. The workspace is infinite; exported artifacts are bounded.
2. Artboards are first-class editor objects, even if they are still backed by scene pages in V0.
3. The active artboard is the current editing and export target.
4. Viewport state is UI state, not document state.
5. Child geometry remains artboard-local canonical design points.
6. Backgrounds should read as artboard fills, not oversized loose rectangles.
7. Diagnostics must be visible at the artboard level before a user opens details.
8. CanvasKit and Konva must present the same workspace semantics.

## Terminology

- `page`: The current scene model object that owns nodes and canonical layout size.
- `artboard`: The editor-facing bounded frame backed by a page in V0.
- `frame`: The visible drawable boundary for an artboard. In V0, each page has exactly one frame.
- `workspace`: The infinite editor coordinate space that contains synthesized artboard placements.
- `workspace rect`: The editor-only `{ x, y, width, height }` rectangle for an artboard in workspace coordinates.
- `artboard-local coordinates`: Canonical layout coordinates inside one artboard/page.
- `screen coordinates`: Browser pixel coordinates after workspace pan and zoom.
- `activeArtboardId`: Editor-facing name for the selected page/artboard. It aliases the existing `activePageId` in V0.

## UX Target

The editor should open directly into the working surface, not a marketing or preview page. The first viewport should read as:

- Dark left rail with artboards/pages and layers.
- Medium dark grey center workspace with one or more bounded drawable frames/artboards.
- Dark right panel with inspector, agent, export, and diagnostics modes.
- Compact top context bar showing the active artboard name, size, and mode.
- Floating bottom toolbar for select, pan, zoom, fit current, fit all, diagnostics, and export preview.

The central workspace should look like a professional design tool surface:

- Medium dark grey background, not the current page-sized preview shell.
- Artboards/frames cast a restrained shadow and have clear bounds.
- The drawable frame surface uses the scene page fill when present and a neutral white/default page fill otherwise.
- Artboard labels sit just above the top-left edge and do not scale awkwardly.
- The active artboard has a clear outline or label state.
- Artboards with diagnostics have a compact status badge.
- Empty surrounding workspace is usable panning space.

## Editor Shell

### Left Panel

The left panel combines the current page rail and layer panel into a dark editor rail:

- Artboard list at the top.
- Layer tree for the active artboard below.
- Each artboard item shows name, size label, and status indicator.
- Clicking an artboard activates it and pans/fits only when the user explicitly chooses fit.
- Double-click or context actions may remain future work unless existing page actions already support them.
- Existing add, duplicate, and remove page actions remain available but should be styled as compact icon actions.

The layer tree remains scoped to the active artboard in V0. Cross-artboard layer browsing is deferred.

### Top Context Bar

The top context bar replaces the current heavy preview controls with compact editor context:

- Active artboard label.
- Active artboard canonical size.
- Current zoom percentage.
- Mode switch: `Edit`, `Agent`, `Export`, `Diagnostics`.
- Optional renderer/status chip when useful for development.

The mode switch controls which right-panel surface is primary. It must not unmount document state or reset the workspace viewport.

### Right Panel

The right panel is dark chrome with content surfaces for:

- Inspector: node/artboard details and editing controls.
- Agent: current chat panel.
- Export: export profile, selected artboard/all artboards scope, preview result.
- Diagnostics: preflight and validation results grouped by artboard and node.

Existing inspector/export/agent/validation components should be reused and restyled where possible. Branch 2 should not rewrite domain logic just to satisfy the shell.

### Bottom Toolbar

The bottom toolbar floats over the lower center workspace:

- Select tool.
- Pan/hand tool.
- Zoom out.
- Zoom level.
- Zoom in.
- Fit current artboard.
- Fit all artboards.
- Diagnostics toggle or status.
- Export preview/open export mode.

The toolbar is icon-first with tooltips. Text labels may be used only where the command is ambiguous or already established in the product.

## Workspace Model

Branch 2 introduces a derived workspace view model:

```ts
type EditorMode = "edit" | "agent" | "export" | "diagnostics";
type WorkspaceTool = "select" | "hand";
type WorkspaceFitTarget = "current" | "all";

interface WorkspaceArtboard {
  pageId: string;
  name: string;
  label: string;
  layoutWidth: number;
  layoutHeight: number;
  exportLabel?: string;
  workspaceRect: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
  isActive: boolean;
  diagnosticsSummary: {
    errorCount: number;
    warningCount: number;
  };
}

interface WorkspaceViewport {
  zoom: number;
  panX: number;
  panY: number;
}
```

The exact type names can follow local conventions, but these concepts must exist as explicit editor contracts.

## Workspace Placement

For V0, workspace placement is deterministic and derived from scene page order. It is not persisted into the scene.

Rules:

- Each page becomes one artboard.
- Each page has exactly one visible drawable frame in V0.
- Artboard size comes from canonical layout dimensions, not physical mm/in metadata.
- Placement is stable for the same ordered page list.
- Placement leaves enough gap for labels, resize handles, shadows, and diagnostics badges.
- Placement supports differently sized artboards in one scene.
- Placement returns a bounding rect for `fit all`.

Recommended V0 placement:

- Sort by scene page order.
- Lay artboards left-to-right with a fixed workspace gap.
- Wrap to a new row when the current row exceeds a large target row width.
- Align each row to its top edge.
- Start near workspace origin with positive coordinates, but allow pan to reveal all surrounding empty space.

This is a view concern. Operations that move scene nodes must never update workspace placement.

## Coordinate Contract

All interactive math must make the coordinate spaces explicit:

```txt
screen -> workspace -> artboard-local -> scene node
scene node -> artboard-local -> workspace -> screen
```

Branch 2 must provide shared helpers for:

- Screen to workspace point.
- Workspace to screen point.
- Workspace point to artboard-local point.
- Artboard-local rect to workspace rect.
- Artboard-local rect to screen rect.
- Workspace bounds for one artboard.
- Workspace bounds for all artboards.

Renderer adapters consume these helpers. They should not each invent their own pan/zoom/page origin math.

## Rendering Contract

`EditorCanvas` remains the renderer switch, but it should now switch between two workspace-capable renderer adapters:

- Konva workspace adapter.
- CanvasKit workspace adapter.

Both adapters must:

- Render all visible artboards, not only the active page.
- Render the active artboard state consistently.
- Clip nodes to their artboard bounds.
- Render labels, guides, safe area, bleed, and diagnostics badges in equivalent positions.
- Use the same viewport state.
- Use the same coordinate transform helpers.
- Emit the same scene operations for drag/resize/text edits.
- Never scale scene coordinates by physical export units.

### Konva

The Konva path should evolve from the current single-page `CanvasSurface` into a multi-artboard workspace:

- The stage uses workspace pan/zoom.
- Each artboard is a group at `workspaceRect.x/y`.
- Page children render in artboard-local coordinates inside that group.
- Clipping is applied at the artboard group boundary.
- Selection overlays and transformers account for artboard origin plus workspace pan/zoom.

### CanvasKit

The CanvasKit path must reach V0 parity:

- It uses the same workspace model and viewport state as Konva.
- `CanvasKitStage` renders each artboard at its workspace rect.
- Drawing is clipped to the artboard rect before rendering page children.
- DOM/SVG overlays use the same workspace/artboard transforms.
- Pointer hit-testing converts through screen, workspace, and artboard-local space.

The existing CanvasKit fit-to-page limitation must be retired for this branch.

## Selection And Tools

Selection rules:

- Clicking an artboard background activates that artboard.
- Clicking a node selects the node and activates its artboard.
- Clicking empty workspace clears node selection but preserves the active artboard unless an explicit deselect-all behavior already exists.
- Node selection cannot cross artboards in V0.
- Artboard selection is represented by `activeArtboardId`; separate multi-artboard selection is deferred.

Tool rules:

- Select tool enables normal node/artboard selection and scene edits.
- Hand tool pans the workspace.
- Spacebar-drag may pan if it fits current editor conventions.
- Wheel/pinch zooms around pointer when feasible; otherwise zooms around viewport center.
- Fit current frames the active artboard.
- Fit all frames all artboards and their labels.

## Export UX

The export panel and export action should use artboard language:

- Default export scope: selected/active artboard.
- Secondary scope: all artboards.
- Future scope: named selection or custom set.

Implementation can continue to call the API with `pageIds`, but the UI copy and state should read as artboards. Exporting the selected artboard must not depend on the scene dimensions or workspace bounding box.

## Diagnostics UX

Diagnostics are artboard-aware:

- Left artboard list shows error/warning indicators.
- Artboard label or badge shows aggregate status.
- Diagnostics panel groups results by artboard, then node.
- Selecting a diagnostic activates its artboard and selects the node when applicable.
- Fit current should work after diagnostic selection.

Preflight remains the source of truth for validity. Branch 2 only improves visibility and navigation.

## Compatibility

Branch 2 must preserve:

- Existing scene load/save semantics.
- Existing operation payloads for node edits.
- Existing export API shape where it still expects `pageIds`.
- Existing feature flag behavior for CanvasKit vs Konva.
- Existing agent chat API integration.
- Existing page add/duplicate/remove semantics.

## Acceptance Criteria

The branch is acceptable when:

- Multiple differently sized artboards are visible in the editor at once.
- The active artboard can be selected from the workspace and the left panel.
- Nodes remain editable inside their artboard in both Konva and CanvasKit modes.
- Artboard clipping prevents page children from drawing into neighboring workspace area.
- Fit current and fit all work from the bottom toolbar.
- Export selected artboard calls the existing export flow with the correct page/artboard id.
- Diagnostics are grouped or surfaced by artboard.
- Viewport changes do not emit scene operations or mutate scene geometry.
- CanvasKit and Konva render the same artboard placement and selection semantics under the feature flag.
- The visual shell matches the intended direction: dark side panels, medium dark grey central workspace, bounded drawable frames/artboards, compact top context, and floating bottom toolbar.

## Deferred Decisions

- Persisting custom artboard positions in scene metadata.
- Multi-artboard selection and batch operations.
- Loose workspace objects outside artboards.
- Artboard-as-frame compiler generation.
- Layout-cluster repair actuator.
- Browser screenshot acceptance with Codex Browser plugin.
- Full responsive redesign for tablet/mobile editor use.
