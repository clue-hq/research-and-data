# Subsystem Map: Editor modes, gestures & selection (frontend)

Scope: how the editor today lets (or refuses to let) a human directly move/resize/rotate/select
nodes, what an interaction translates into at the engine-op level, and what would have to change to
build the user's two modes (FREEHAND vs LAYOUT-MANAGED editing) plus the agent round-trip.

Everything below is split into **EXISTS TODAY** vs **MISSING / WOULD NEED BUILDING**. Speculation is
labeled.

---

## 1. "Editor modes" — what actually exists

### `editorModes.ts` is NOT about interaction modes (important)
`apps/editor/src/engine/editorModes.ts:1-29` defines only **right-sidebar panel** modes:

```ts
export type EditorPanelMode = "inspector" | "agent" | "export" | "diagnostics";
```
(`editorModes.ts:1`, list at `:10-15`, label helper at `:17-28`). A `FutureEditorPanelMode` adds
`"personalization"` (`:2`). There is **no** freehand/absolute/free/layout interaction mode here. The
file name is misleading for this study: it is purely "which inspector panel is open."

### The only true interaction "mode" is the workspace tool
`apps/editor/src/engine/workspaceViewport.ts:11`:
```ts
export type WorkspaceTool = "select" | "hand";
```
- `"select"` — pointer hits select/drag/resize/rotate/marquee.
- `"hand"` — pointer pans the workspace (no node interaction); wired at
  `CanvasKitCanvas.tsx:614-628` (pan drag) and toolbar buttons `:533-552`.

That is the complete set of "modes." **There is no toggle that turns layout management off, no
absolute/freehand mode, no per-node "free positioning" flag.** (Verified by grep across
`apps/editor/src` for `freehand|absolute|free mode|interactionMode|editMode|canvasMode|positioning`
— only CSS `position:absolute` and prose hits, no toggle.)

### What "editing" is permitted today
Editing is **always layout-managed** in the sense that positions are *solved* by the engine. Direct
geometry edits are permitted **only** when a node is *not* an auto-layout child and *not* locked
(see §4). When permitted, a drag writes the node's `transform.x/y` (its position relative to its
parent), which the solver then honors for frame/group/page parents. So "freehand-ish" behavior
already exists for non-auto-layout subtrees; it just isn't a mode and isn't labeled.

---

## 2. Two canvases, one gesture/op vocabulary

`EditorCanvas.tsx:44-71` is a flag switch:
- `canvasKitFlagEnabled()` → `CanvasKitCanvas` (immediate-mode Skia + custom gesture machine).
- otherwise → `CanvasSurface` (retained-mode Konva).

**Both** translate drag/resize/rotate through the **same** operation builders
(`canvasDragOperation`, `canvasResizeOperation` in `engine/canvasOperations.ts`) and gate on the
**same** predicate `isNodeDirectGeometryEditable`. So findings here apply to both renderers.

- Konva path: `components/canvas/SceneNode.tsx:66-109` (`handleDragEnd`, `handleTransformEnd`),
  `draggable={directGeometryEditable}` at `:120`.
- CanvasKit path: `CanvasKitCanvas.tsx:360-425` (`applyAction`) over the pure
  `gestureReducer`.

---

## 3. Gestures (CanvasKit path) — pointer → engine op trace

### State machine (`engine/gestureMachine.ts`)
Pure reducer `(state, event) → { state, action }` (`gestureMachine.ts:78-87`). States
(`:54-60`): `idle | pressed | dragging | resizing | rotating | marquee`. Actions (`:62-68`):
`select | drag | resize | rotate | marquee` (each with a `committed` flag).

Flow:
1. **down** (`onDown`, `:89-102`): selecting happens on press, Figma-style. Press on a `node` →
   `select` (additive if `meta`); press on `empty` (no meta) → clear selection. State → `pressed`.
2. **move** while `pressed` (`onMove`, `:104-124`): if movement `< DRAG_THRESHOLD` (3px,
   `:31`) it stays a click (no-op). Past threshold → `beginGesture` promotes the press into the
   matching gesture based on what was grabbed (`:147-178`).
3. The grab target (`PressTarget`, `:42-47`) is `node | handle | rotate | empty` — decided by the
   host's hit test (see below). So a node press becomes `dragging`, a handle press becomes
   `resizing`, the rotate handle becomes `rotating`, an empty press becomes `marquee`.
4. **up** (`onUp`, `:126-145`): emits the same action with `committed: true`, returns to `idle`.

### What each gesture computes (still descriptor-space geometry, not engine ops yet)
- **drag** (`dragAction`, `:180-193`): pure translation — `box.x = startBox.x + dx`,
  `box.y = startBox.y + dy`. **It only translates; it does NOT reorder children or change parent.**
- **resize** (`resizeAction`, `:195-206`): delegates to `resizeBox` (transformer math, §5).
- **rotate** (`rotateAction`, `:208-220`): `startRotation + angleDelta`, Shift snaps to 15°
  (`ANGLE_SNAP_STEP`, `:33`), normalized to [0,360).
- **marquee** (`:119-120`, commit `:138-140`): `rectFrom` builds an AABB; `marqueeSelection`
  (`:237-239`) returns nodes whose render box intersects (`rectsIntersect`, `:241-248`).

### Host wiring (`components/canvas/CanvasKitCanvas.tsx`)
- `pressTargetFor` (`:301-329`): handle-grab on the current selection takes priority
  (`handleAtPoint`), else engine `hitTest` resolves the node under the pointer. Handles are only
  considered when `showHandles` is true (`:304`).
- `dispatch` (`:427-434`) runs the reducer and calls `applyAction`.
- `applyAction` (`:360-425`) is where actions become **engine operations**:
  - `drag`: live preview via `setPreview` while moving; on `committed`, calls
    `dragActionToOperation(...)` → `onOperation(op)` (`:367-378`).
  - `resize`: same pattern → `resizeActionToOperation` (`:379-391`).
  - `rotate`: reuses `resizeActionToOperation` with the new rotation, keeping the box
    (`:392-403`).
  - `marquee`: selects the topmost intersecting node (`:404-419`) — **note: despite supporting
    multi-hit math, it currently selects a single node** (`hits[hits.length-1]`), see §6.
  - `select`: `onSelectNode` (`:364-365`).

### Other gestures
- **Double-click** (`onDoubleClick`, `:471-491`): on a text node → enter text edit
  (`setEditingNodeId`); otherwise drill selection up to `topLevelAncestorId` (the whole card/group).
- **Wheel** (`:592-609`): ctrl/meta = zoom at cursor, else pan.
- **Pan tool drag** (`:614-628`, `:659-688`).

### THE OP: drag → `updateNodeTransform`
`canvaskitGestures.ts:78-95` `dragActionToOperation` → `canvasOperations.ts:26-62`
`canvasDragOperation`:
- **First gate:** `if (!isNodeDirectGeometryEditable(scene, node.id) ...) return null;`
  (`canvasOperations.ts:41`). Layout-managed/locked → drag produces **nothing**.
- Converts descriptor box top-left back to scene units (`sceneUnitFromCanvas`), snaps to parent
  edges/center/safe-area guides (`snapTransformToGuides`, `:128-151`; 6px threshold `:11`),
  clamps inside parent bounds (`clampNodeTransformToParentBounds`).
- Emits `updateNodeTransform(node, nextTransform)` = `update_node` patch setting `transform`
  (`operations.ts:236-244`). **It sets `transform.x/y` only — never changes parent or sibling
  order.**

### THE OP: resize → `updateNodeTransformAndSize`
`canvaskitGestures.ts:99-124` `resizeActionToOperation` → `canvasOperations.ts:64-114`
`canvasResizeOperation`:
- Same `isNodeDirectGeometryEditable` gate (`:77`).
- Expresses new size as `scaleX/scaleY` over the node's base render size, converts to scene units,
  clamps to parent bounds, then emits `updateNodeTransformAndSize` — which sets `transform` **and**
  forces `size.width/height` to `{ kind: "fixed", value }` (`operations.ts:294-303`,
  `canvasOperations.ts:104-113`). **Side effect worth flagging: any canvas resize collapses a
  `hug`/`fill` dimension into a `fixed` one.**

### Does drag reorder or move freely?
- **Move freely:** Yes, *within the parent*, but only for non-auto-layout subtrees; the new `x/y`
  is clamped to the parent's bounds. There is **no reparenting on drag** and **no z-order/sibling
  reorder on drag**. (`move_node` exists in the engine — `operations.rs:505-554` — but no gesture
  ever calls it.)
- **Reorder:** Not via canvas drag. Layer reorder is referenced in copy
  (`canvasSelection.ts:25`) but is a separate control, not a gesture here.

---

## 4. The gate: `isNodeDirectGeometryEditable` (the wall the user hit)

`engine/sceneQueries.ts:183-192`:
```ts
export function isNodeDirectGeometryEditable(scene, nodeId): boolean {
  const node = scene.nodes[nodeId];
  if (!node || node.locked) return false;
  return !isNodeLayoutManaged(scene, nodeId);
}
```
`isNodeLayoutManaged` (`sceneQueries.ts:172-181`): true iff the node's **direct parent node is an
`auto_layout`**. (Page/frame/group parents are NOT "layout-managed" by this definition.)

Consequences, all driven by this single predicate:
- **Canvas:** `pressTargetFor` won't offer handles (`CanvasKitCanvas.tsx:304` `showHandles`);
  Konva `draggable={directGeometryEditable}` (`SceneNode.tsx:120`); the op builders early-return
  `null` even if a gesture fires (`canvasOperations.ts:41,77`).
- **Inspector:** X/Y/W/H/Rotate fields `disabled={!directGeometryEditable}`
  (`InspectorPanel.tsx:248-279`). A muted note explains why (`:299-305`).
- **User messaging:** `canvasDirectEditNotice` (`canvasSelection.ts:14-29`) returns the human
  string ("Selection is managed by an auto-layout parent…" / "Selection is locked…"), rendered as
  the `DisabledNotice` chrome in `SelectionOverlay.tsx:133-135,293-304`.

**This is exactly the user's prior failure: anything inside an auto-layout is hard-blocked from
direct drag/resize because its position is solved, and the editor deliberately disables the path
rather than fight the solver.** Note importantly: nodes inside `frame`/`group`/`page` are NOT
blocked — they already drag freely via `transform.x/y`. The wall is specifically auto-layout
children.

### What edits ARE allowed for layout-managed nodes today
Only `disabled={selectedNode.locked}` (not `directGeometryEditable`) gates these, so they work
inside auto-layout:
- Opacity (`InspectorPanel.tsx:281-297`), fills/fill color (`:380-387`), strokes (`:388+`),
  name, delete, sizing **mode** (fixed/hug/fill, the note at `:370-373` explicitly says
  "layout-managed children can change sizing mode even when their direct X/Y geometry is locked"),
  auto-layout alignment/gap/padding for the parent.
- Text content via double-click overlay (`CanvasKitCanvas.tsx:493-500` → `updateTextNode`).

So the user's wish-list of **recolor / opacity / font / color edits already works** regardless of
layout management. The blocked items are specifically **drag/resize/rotate/crop of auto-layout
children** and **reparenting/free positioning**.

---

## 5. `transformerMath.ts` — does it produce absolute deltas or layout changes?

Pure geometry over canvas-space boxes (`transformerMath.ts:1-14` header is explicit: "no renderer,
no scene"). It produces **a new descriptor-space `Box` (absolute geometry)** — never a layout
input.

- `resizeBox` (`:69-138`): drags a handle, anchors the opposite corner/edge, enforces min size
  (default 2, `:48`), optional aspect lock on corner handles (`:104-125`), and respects rotation by
  resizing in the box's LOCAL unrotated frame about its top-left origin (`:80-81,129-137`). Output
  is `{x,y,width,height}` in world/descriptor space.
- `rotatePoint` (`:52-60`), `angleFromPivot` (`:142-144`), `snapAngle` (`:147-152`),
  `normalizeAngle` (`:155-158`), `handlePoint` (`:162-167`) place handles on a rotated box.

The math is **absolute**: it yields a target box. The *translation into the layout model* happens
later in `canvasOperations.ts` (scale-factor → `fixed` size, x/y → `transform`). So transformerMath
itself is mode-agnostic and would be **fully reusable by a freehand mode** — it already gives you
the absolute box a freehand drag/resize wants. (`handleAtPoint` for hit-testing handles lives in
`canvaskitGestures.ts:50-75`.)

---

## 6. Selection — single/multi, container vs child

### Single vs multi
- **State is single-select.** Both canvases carry `selectedNodeId: NodeId | null`
  (`CanvasKitCanvas.tsx:64`, `EditorCanvas.tsx:26`), `onSelectNode(nodeId | null)`.
- The gesture machine's `select` action carries an `additive` flag (`gestureMachine.ts:64`,
  set from `meta` in `onDown` `:94`) and `marqueeSelection` returns an **array**
  (`:237-239`) — i.e. the primitives anticipate multi-select — **but the host collapses to one**:
  marquee commit picks `hits[hits.length-1]` (`CanvasKitCanvas.tsx:414`) and the additive flag is
  dropped when calling `onSelectNode` (`:365`, single id). **MISSING: true multi-select.**

### Selection on press, drill on double-click
- Single click selects the deepest hit node (engine `hitTest`, `pressTargetFor` `:317-325`).
- Double-click drills up to the **top-level container** via `topLevelAncestorId`
  (`sceneQueries.ts:150-170`; double-click handler `CanvasKitCanvas.tsx:488-490`; Konva equivalent
  `SceneNode.tsx:59-64`). This is "container vs child" targeting.

### Container chrome
When the selection is a container that holds children (`isContainerNode`, `sceneQueries.ts:36-38`),
the canvas draws distinct chrome — a labeled box + faint outlines of each direct child — so a user
sees "I grabbed a container of N elements" before dragging the whole subtree:
- Geometry: `containerSelectionGeometry` (`canvasSelection.ts:56-76`) reads `computed.layout_bounds`
  for the container and each child.
- CanvasKit chrome: `SelectionOverlay.tsx:78-99` (children + label); host wiring
  `CanvasKitCanvas.tsx:723-724,750-811`.
- Konva chrome: `ContainerSelectionOverlay.tsx:28-102`.

### Selection chrome model
`selectionChrome.ts:59-87` `deriveSelectionChromeModel` is the single source of truth for what the
overlay shows: `selectionBox`/`hoverBox` from `computed.layout_bounds` (`:183-198`), `showHandles =
isCanvasDirectGeometryEditable` (`:79`), `disabledReason` (`:66`), slot/diagnostic badges. **Hover**
is single-node, DOM/SVG only, recomputed per pointer move (`CanvasKitCanvas.tsx:331-358`).

---

## 7. Where a "freehand toggle" would live, and what blocks free drag/resize

### How close is the current code?
**Surprisingly close for the gesture/render layer; the block is entirely in the data model + one
predicate.**

What already works in favor of freehand:
1. The gesture machine, transformer math, handle hit-testing, preview rendering, and SVG chrome are
   all **mode-agnostic** and operate on absolute boxes. A freehand mode needs *no new gesture code*.
2. Non-auto-layout subtrees (frame/group/page children) are **already freely draggable/resizable**
   via `transform.x/y` + `fixed` size — the engine honors explicit `transform.x/y` for these parents
   (`layout.rs:142-150` page children, `:186-192` frame/group children, `:359-372` non-auto
   children, absolute write at `:862-863`).
3. The engine **already has an "out-of-flow" escape inside auto-layout**: an auto-layout child that
   is rotated/skewed is *excluded from flow* and positioned by its explicit `transform.x/y`
   (`layout.rs:264-280` exclusion; `:340-357` positions excluded children at
   `origin + child.transform`; `is_out_of_flow_transform` at `:1508-1512`). Test proof: a rotated
   auto-layout child lands at exactly its `transform.x = 100` (`tests/layout_engine.rs:766-789`).
   **This is the mechanism nearest to "freehand within a managed parent" — but today it's only
   triggered by rotation/skew, not by an explicit intent flag.**

### What blocks free drag/resize for auto-layout children (the real list)
1. **No "ignore layout / absolute position" flag on a node.** `Node` has `transform`, `size`,
   `layout` (auto-layout props *for containers*), `locked` — but **no `position: absolute` /
   `out_of_flow` / `pinned` boolean** that a leaf can carry to opt out of its parent's flow
   (`contracts.ts:161-181`; `Transform` is geometry-only `:390-398`; `Dimension` has no absolute
   mode `:405+`). The only opt-out is the implicit rotation/skew hack.
2. **The hard gate.** `isNodeDirectGeometryEditable` returns false for any auto-layout child
   (`sceneQueries.ts:183-192`); it's consulted by the canvas, the op builders, and the inspector.
   Free drag is impossible until this predicate (and what it gates) understands a freehand intent.
3. **Resize collapses sizing modes.** Canvas resize hard-writes `fixed` width/height
   (`canvasOperations.ts:104-113`) — fine for freehand, but it silently destroys `hug`/`fill`
   semantics the agent relied on.
4. **No multi-select / group transform** (`CanvasKitCanvas.tsx:414`), so freehand on multiple nodes
   isn't expressible yet.
5. **No reparent-on-drag.** `move_node` exists in the engine (`operations.rs:505-554`) but no
   gesture emits it; dragging a node out of one container into another is not wired and the engine's
   `move_node` does **not** adjust `transform` to preserve world position.

### MISSING (build list for a freehand toggle), labeled
- **Data model:** an explicit per-node (or per-subtree) "free / absolute / out-of-flow" flag, plus
  solver support so the flag positions the node by `transform.x/y` relative to its parent (reusing
  the existing out-of-flow code path, generalized from "rotated" to "flagged"). *(Speculative design
  — not present today.)*
- **Predicate:** `isNodeDirectGeometryEditable` must treat a flagged node as editable
  (`sceneQueries.ts:183`).
- **Mode state + UI:** a real interaction mode (extend `WorkspaceTool` or add a new mode type — note
  `editorModes.ts` is the wrong file, it's panels) and a toggle control; on toggle, write the flag
  (and seed `transform.x/y` from current `computed.layout_bounds` so the node doesn't jump).
- **Reparent-on-drag** wiring to `move_node` with world-position preservation (recompute
  `transform.x/y` against the new parent's origin).
- **Multi-select + group transform.**

---

## 8. Editing implications & round-trip

### Human freehand editing
- For **frame/group/page** children, freehand-style editing is **already live** — drag/resize/rotate
  write `transform.x/y` + `fixed` size and the solver honors them. The user's "prior attempt failed
  because everything is layout-managed" is really "everything authored as **auto-layout** is solved."
  A freehand mode is mostly about (a) letting auto-layout children opt out, and (b) not destroying
  the agent's layout intent when they do.
- The cheapest correct primitive already exists in the engine: the **out-of-flow positioning path**
  (`layout.rs:340-357`). Generalize its trigger from "rotated/skewed" to "has an explicit free/pinned
  flag," and freehand-within-auto-layout becomes a small, solver-consistent change rather than a
  parallel positioning system.
- Recolor / opacity / font / color edits the user wants are **not gated by layout** at all
  (`InspectorPanel.tsx`, gated only by `locked`); those already round-trip cleanly as `update_node`
  patches.

### The agent round-trip (the hard question)
Two facts from this subsystem determine the answer:

1. **Every human edit is already a canonical `update_node` operation** against the shared scene
   (`operations.ts`), the *same* op vocabulary the agent uses (`apply_operations` /
   `compile_dsl_block` in `agent_runtime/lumen_deepagent/tools.py:277+`). So a human freehand drag
   produces `transform: set({x,y,...})` — a first-class, replayable mutation, not an out-of-band
   blob. **This is the strongest enabler of the round-trip: human and agent speak the same
   operation language.**

2. **BUT there is no scene→DSL serializer.** The Rust core parses DSL→scene
   (`dsl.rs`) and applies ops→scene (`operations.rs`), but I found **no `to_dsl` / scene emitter**
   anywhere in `crates/` (grep for `to_dsl|serialize|emit_dsl|scene_to_dsl` → nothing). The agent
   authors *forward*: it starts from `new_scene` and appends DSL continuations / structured ops,
   keeping a `dsl_session.session_snapshot` (`tools.py:139,236-237`). It has **no ingest path** that
   reads an arbitrary (human-modified) scene back into its DSL working set.

**Implication for "can the agent take it back?":**
- If the agent operates on the **scene + structured operations** (the `apply_operations` path), the
  round-trip is *representationally fine today*: a freehand human edit is just more `transform`/`size`
  patches on the same scene the agent already reads. A freehand "free/absolute" flag would need to be
  (a) representable in the scene contract and (b) understood by the agent's repair logic so it doesn't
  clobber a human's manual position.
- If the agent relies on its **DSL session snapshot** to reason/edit (which the tooling strongly
  implies — `dsl_session` is threaded through every compile, `tools.py:212-237`), then a human
  freehand edit made through the *canvas* mutates the scene **without updating the DSL session**, so
  the agent's authoritative source (DSL) and the real scene **diverge**. With no scene→DSL emitter,
  the agent cannot re-derive DSL from the human-edited scene. **This is the core round-trip gap:
  there is no canonical way to project a human-modified scene back into the agent's authoring
  representation.**

**What representation makes the round-trip possible (synthesis, partly speculative):**
- Make the **scene the single source of truth** for both human and agent, with structured operations
  (not DSL text) as the shared mutation log — the editor already does this; the agent's
  `apply_operations` path already does this. Demote the DSL session from "source of truth" to "a
  convenience input," OR build a **scene→DSL emitter** so the agent can re-synchronize after human
  edits.
- Represent freehand positioning **inside the existing model** (an explicit out-of-flow/pinned flag
  routed through `layout.rs`'s existing out-of-flow path) rather than as a separate absolute layer,
  so the agent's layout reasoning still applies and a human's pin is just one more declared property
  the agent can read, respect, or deliberately override.

### Realistic scope (frontend interaction layer only)
- **Reusable as-is:** gesture machine, transformer math, handle hit-test, preview, SVG chrome,
  container chrome, hover, the op builders' snapping/clamping. No new interaction code needed for
  single-node freehand.
- **Net-new (frontend):** a real mode toggle (NOT in `editorModes.ts`), seeding `transform.x/y` from
  `computed` on toggle, multi-select + group transform, reparent-on-drag → `move_node`, and undoing
  the "resize collapses hug/fill" behavior when in managed mode.
- **Net-new (engine/agent), the gating dependency:** the out-of-flow flag in the contract + solver,
  and either a scene→DSL emitter or an agent that treats scene+ops as authoritative — without one of
  those, the human→agent round-trip cannot close.

---

## Appendix — file:line index

- Panel modes (not interaction modes): `engine/editorModes.ts:1,10-15`
- Workspace tool (select/hand): `engine/workspaceViewport.ts:11`
- Gesture reducer: `engine/gestureMachine.ts:78-87`; states `:54-60`; actions `:62-68`;
  drag math `:180-193`; resize `:195-206`; rotate `:208-220`; marquee `:119-120,138-140,237-248`;
  DRAG_THRESHOLD `:31`; ANGLE_SNAP_STEP `:33`
- Host glue: `engine/canvaskitGestures.ts` — handle hit-test `:50-75`; drag→op `:78-95`;
  resize→op `:99-124`
- Transformer math: `engine/transformerMath.ts:69-138` (resizeBox), `:142-167` (angles/handles)
- Op builders + gate + snapping/clamping: `engine/canvasOperations.ts:26-114` (gate `:41,:77`)
- Operations: `engine/operations.ts:236-244` (updateNodeTransform), `:294-303`
  (updateNodeTransformAndSize), `:356-363` (moveNodeToParent)
- Gate predicates: `engine/sceneQueries.ts:172-181` (layoutManaged), `:183-192` (directEditable),
  `:150-170` (topLevelAncestorId), `:36-38` (isContainerNode)
- Selection model/notice/geometry: `engine/selectionChrome.ts:59-198`;
  `engine/canvasSelection.ts:10-76`
- CanvasKit host: `components/canvas/CanvasKitCanvas.tsx:360-425` (applyAction),
  `:301-329` (pressTargetFor), `:471-491` (double-click drill/text edit),
  `:404-419` (marquee single-collapse `:414`)
- Konva host: `components/canvas/SceneNode.tsx:66-109,120,131-132`
- Overlays: `components/canvas/SelectionOverlay.tsx:52-174`;
  `components/canvas/ContainerSelectionOverlay.tsx:28-102`
- Inspector gating: `components/InspectorPanel.tsx:193-194,248-279,299-305,370-373`
- Contracts: `engine/contracts.ts:161-181` (Node), `:373-398` (AutoLayout/Transform),
  `:405-` (Dimension)
- Engine solver: `crates/lumen-core/src/layout.rs:142-150,186-192,264-280,340-372,862-863,1508-1512`
- Out-of-flow proof test: `crates/lumen-core/tests/layout_engine.rs:766-789`
- Engine move_node (reparent, no transform fix): `crates/lumen-core/src/operations.rs:505-554`
- DSL position lowering: `crates/lumen-core/src/dsl.rs:2344-2348`
- Agent edit paths (DSL session + structured ops): `apps/agent_runtime/lumen_deepagent/tools.py:170-300`
- No scene→DSL emitter: grep across `crates/` for `to_dsl|serialize|emit_dsl|scene_to_dsl` → none
