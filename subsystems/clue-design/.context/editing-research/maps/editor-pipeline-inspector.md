# Subsystem map: Editor edit pipeline & inspector (frontend)

Scope: how UI property edits and canvas gestures flow into the WASM engine and
back to the rendered scene; which properties are editable today; how edits are
batched / persisted / undone; the optimistic-vs-authoritative model; crop &
opacity state; and the round-trip implications for human freehand editing.

All paths relative to `apps/editor/src`. "Today" = present in this tree.
"Missing" = not present, would need building. Speculation is labeled.

---

## 1. The edit pipeline, end to end

There are TWO distinct edit entry points, and they both converge on the SAME
single function: `applyOperations` in `EditorApp.tsx`. Everything is an
`Operation` (the raw wire op), NOT a structured edit.

### 1a. Inspector (property) edits

`InspectorPanel` receives `onOperation: (operation: Operation) => void` and
`onOperations?: (operations: Operation[]) => void` as props
(`components/InspectorPanel.tsx:64-66`). Every field's `onChange`/`onCommit`
builds an `Operation` via a helper from `engine/operations.ts` and calls
`onOperation(...)`.

Examples:
- Font size: `onCommit={(value) => onOperation(updateTextNode(selectedNode, { font_size: value }))}` (`InspectorPanel.tsx:732`)
- Fill color: `onOperation(updateNodeFills(selectedNode, [solidFill(...)]))` (`InspectorPanel.tsx:385`)
- Opacity: builds an inline `update_node` op with `nodePatch({ opacity: set(value) })` (`InspectorPanel.tsx:288-296`)
- X/Y/W/H/Rotate: `emitTransform({ x })` → `updateNodeTransform` (`InspectorPanel.tsx:202-204`, `247-280`)

`onOperation` is wired to `applyOperation` (`EditorApp.tsx:1360`), which calls
`applyOperations([operation])` (`EditorApp.tsx:436-438`).

`SlotInspector` is mounted inside `InspectorPanel` (`InspectorPanel.tsx:825-831`)
and uses the same `onOperation`/`onOperations`. Slot edits emit `upsertSlot`,
`removeSlot`, `unbindNodeFromSlot`, and (for "Apply preview") `updateTextNode`
content ops (`SlotInspector.tsx:60-77`, `62`).

`LayerPanel` reorder buttons emit `moveNodeToParent(node.id, parentInfo.parent,
index±1)` (`LayerPanel.tsx:116,130`) — also through `onOperation` →
`applyOperation`.

### 1b. Canvas (gesture) edits

The CanvasKit canvas drives a gesture state machine (`engine/gestureMachine.ts`,
consumed in `components/canvas/CanvasKitCanvas.tsx:17`). During a drag/resize the
canvas only updates a LOCAL visual preview (`setPreview(...)`,
`CanvasKitCanvas.tsx:375,388,400`) — no engine op. On COMMIT it builds an
`Operation` and emits it once:

```
case "drag":
  if (action.committed) {
    const op = dragActionToOperation(action.box, scene, node, page, pageOrigin);
    if (op) onOperation(op);                       // CanvasKitCanvas.tsx:372-373
  } else { setPreview(...); }                      // CanvasKitCanvas.tsx:375
case "resize":
  if (action.committed) {
    const op = resizeActionToOperation(...);
    if (op) onOperation(op);                        // CanvasKitCanvas.tsx:385-386
  }
```

`dragActionToOperation`/`resizeActionToOperation` wrap
`canvasDragOperation`/`canvasResizeOperation` in `engine/canvasOperations.ts`.
Those produce `updateNodeTransform` (`canvasOperations.ts:61`) or
`updateNodeTransformAndSize` (`canvasOperations.ts:104`). The canvas
`onOperation` is also wired to `applyOperation` (`EditorApp.tsx:1244,1282`).

Inline text editing on canvas emits `updateTextNode(node, { content })`
(`CanvasKitCanvas.tsx:498`).

### 1c. The convergence point: `applyOperations` (`EditorApp.tsx:373-434`)

This is the heart of the pipeline. For a non-empty batch:

1. Grab `engine = engineRef.current` (a `WasmEngine`). If none → emit
   `EDITOR_SERVER_ONLY_MODE` warning and **return without applying anything**
   (`EditorApp.tsx:377-392`). So with no WASM engine there is NO local editing.
2. `previousScene = engine.scene` (the engine snapshot, not the React closure —
   `EditorApp.tsx:394-395`).
3. `result = engine.applyOperations(operations)` — OPTIMISTIC local apply in
   WASM (`EditorApp.tsx:396`).
4. If rejected → `EDITOR_LOCAL_APPLY` error diagnostic, scene unchanged,
   return (`EditorApp.tsx:397-413`).
5. On success: push `{ scene: previousScene, operations }` onto the client undo
   stack (capped 50, `EditorApp.tsx:421-427`), clear redo, append to
   `operationHistory`, clear diagnostics, `setScene(result.scene)`
   (`EditorApp.tsx:421-431`).
6. `enqueueForPersistence(operations)` — async server leg
   (`EditorApp.tsx:432`).
7. `onAccepted?.(result.scene)` callback.

### 1d. WASM optimistic apply (`engine/wasmEngine.ts:248-276`)

`WasmEngine.applyOperations` serializes ops to JSON, calls the wasm
`applyOperations`, parses `{ ok, applied_operations, diagnostics,
inverse_operations, delta }`. On success it merges the engine's **mechanical
scene delta** into the local snapshot with `applySceneDelta`
(`wasmEngine.ts:268`, `153-174`) using structural sharing (unchanged entities
keep referential identity). It returns `inverse_operations` for potential undo.

CRITICAL — re-layout happens INSIDE wasm: the Rust core applies the op, re-runs
the FLEX layout solver, and returns the delta with updated `computed` geometry.
JS does NOT re-run layout; it only merges the delta. Full scene snapshots cross
the boundary only on init/reconcile/undo, never per keystroke
(`wasmEngine.ts:18-33`). The engine relays out on load so `computed` is the
single geometry source (`wasmEngine.ts:197-205`, comment at `289-294` in
`EditorApp.tsx`).

`engine/operations.ts` `nodePatch` mirrors the Rust `node_patch_affects_render`:
a render-affecting patch (transform, size, fills, strokes, effects, corner,
opacity, opacity_token, source_asset_id, asset_placement, clip, layout) sets
`computed: clear()` so stale geometry is invalidated and the engine re-lays-out
(`operations.ts:60-90`).

### 1e. Optimistic vs authoritative (the server leg)

`enqueueForPersistence` (`EditorApp.tsx:352-371`) lazily builds an
`ApiEditQueue` (`engine/editQueue.ts:50`) and calls `enqueueOperations`. Only
runs when `documentId` is set and engine kind is `wasm`
(`EditorApp.tsx:353-359`). The queue:

- Serializes batches in a promise chain, POSTs each to
  `/documents/{id}/operations` with `base_version` for concurrency detection
  (`editQueue.ts:62-106`).
- On rejection (non-200): halts, fetches the authoritative document, fires
  `onReconcile({ kind: "rejected", serverScene, ... })` (`editQueue.ts:108-126`).
- On drain (`pending === 1`): fetches the server document and compares
  `withoutComputed(serverScene)` to `withoutComputed(localScene)`
  (`editQueue.ts:142-171`). `computed` is excluded because the server computes
  geometry under Skia and the browser under the heuristic, so they legitimately
  differ. A mismatch in authored fields → `divergence` event.
- `onReconcile` in EditorApp replaces the local scene with the server scene via
  `replaceScene` and surfaces the diagnostic (`EditorApp.tsx:363-368`).

So: **local apply is optimistic and authoritative-for-render; the server is the
durable authority and silently corrects only on divergence/rejection.** Same
engine on both sides means divergence "should never happen outside concurrent
edits" (`editQueue.ts:11-15,166-169`).

### 1f. Structured edits are present but UNUSED by the editor UI

`engine/structuredEdits.ts` exists (`modifyNodeEdit`, `modifyNodeStacksEdit`,
`moveBeforeEdit`, `moveAfterEdit`, `deleteEdit`, `applyStructuredEdit`, history
fetch/undo/redo, etc.). `WasmEngine.applyStructuredEdit` exists
(`wasmEngine.ts:278-311`). BUT a repo grep shows NO call to `applyStructuredEdit`,
`modifyNodeEdit`, or `modifyNodeStacksEdit` from any non-test component. The only
consumer of `structuredEdits.ts` in app code is `HistoryPanel.tsx:4-9`, which
imports `fetchHistory`, `undoDocument`, `redoDocument`, `HistoryEnvelope` for the
server-side committed-history panel. The live editor edit path is 100%
`Operation`-based, not structured-edit-based. (The structured-edit format is the
backend/agent authority per the file's header comment; the editor uses raw
operations for optimistic apply.)

---

## 2. Properties editable in the Inspector TODAY

### Document level (no node selected) — `InspectorPanel.tsx:81-189`
- Document title, artifact type.
- Page: name; size W/H/unit (preset/orientation read-only); safe-area margin;
  bleed margin; page fill token (when brandTokens present).
- Slot overview (read-only list).

### Node level (node selected) — `InspectorPanel.tsx:206-833`

PRESENT today:
- Name (`234-239`); lock toggle (`216-219`); delete (`220-228`).
- **Transform:** X, Y, W, H, Rotate — each gated by `directGeometryEditable`
  (`246-280`). W/H here emit `updateNodeSize` with `{ kind: "fixed" }`.
- **Opacity:** number field, 0–1, step 0.05, gated only by `locked`
  (`281-297`). Emits `update_node` with `nodePatch({ opacity: set(value) })`.
- **Sizing modes:** width/height mode select (fixed / hug / fill) + the
  matching fixed value or fill weight (`308-369`). Layout-managed children can
  change sizing mode even when X/Y is locked (comment `370-373`).
- **Raw style:** fill color (`<input type="color">`), stroke color, stroke
  width, corner radius all + per-corner TL/TR/BR/BL (`376-488`).
- **Design tokens (when brandTokens):** fill token, stroke token, stroke-width
  token, radius token, **opacity token** (`494-578`).
- **Auto Layout (auto_layout node OR has layout OR layout-managed):** direction,
  wrap, gap, grow, padding T/R/B/L, align X, align Y, gap token, padding token
  (`580-701`).
- **Text (text node):** content (textarea), **font family** (free-text input,
  `720-726`), **font size**, **font weight** (100–900 step 100), align, line
  height, letter spacing, max lines, wrap, direction, and style token
  (`703-823`). Font family is a raw text `<input>` — there is no font picker /
  validated family list.

ABSENT today (NOT in the inspector):
- **CROP / image fit:** NO UI. `ImageFitMode = "contain" | "cover" | "crop"`
  exists (`contracts.ts:646`), `AssetPlacement.fit/focal_point` exists
  (`contracts.ts:361-366`), the `Node.asset_placement` field exists
  (`contracts.ts:176`), and `operations.ts` `nodePatch` passes through
  `asset_placement` and `clip` (`operations.ts:57-58`). But NO inspector control
  edits any of these, and there is NO image-specific inspector section at all
  (there is a `text`, `auto_layout` section but no `image` section). Crop is
  effectively only expressible by raw scene authoring / the agent, not the UI.
- **`clip` boolean:** field exists on `Node` (`contracts.ts:177`) and is
  patchable (`operations.ts:58,87`), but NO inspector control sets it. (The
  word "clip" in the UI is only the slot OVERFLOW policy in `SlotInspector`,
  unrelated to node clipping — `SlotInspector.tsx:339,471`.)
- **Effects / drop shadow editing:** `effects` render (renderAdapter shadows),
  and `modifyNodeStacksEdit`/`effectEdits` exist in `structuredEdits.ts`, but no
  inspector UI edits effects.
- **Gradients:** rendered and patchable, but the color inputs only emit SOLID
  hex fills/strokes (`solidFill`/`solidStroke`, `InspectorPanel.tsx:1256-1283`).
  Selecting a node with a gradient and touching the color picker downgrades it
  to a solid.
- **Reparenting via inspector:** no control. Reorder-within-parent only, via
  LayerPanel arrows (`moveNodeToParent` with same parent ±1).
- **No explicit "make absolute / detach from layout" toggle.** (See §5.)

### Slot inspector — `SlotInspector.tsx`
Mark/unmark slot, key, label, content type, required, placeholder, sample &
worst-case fixtures, max-length fields, overflow policy, "apply preview to text
nodes". Image policy is displayed read-only (`SlotInspector.tsx:355-356,577-583`).

---

## 3. Editability gating (the solver-vs-direct-edit boundary)

`engine/sceneQueries.ts`:
- `isNodeLayoutManaged(scene, nodeId)` = true when the node's parent is an
  `auto_layout` node (`sceneQueries.ts:172-181`).
- `isNodeDirectGeometryEditable` = not locked AND not layout-managed
  (`sceneQueries.ts:183-192`).

Consequences:
- Inspector X/Y/W/H/Rotate fields are `disabled={!directGeometryEditable}`
  (`InspectorPanel.tsx:250-278`). For a layout-managed (auto-layout child) node,
  these are greyed out; the inspector tells the user to "Use layout controls or
  reorder the layer instead of direct geometry edits"
  (`InspectorPanel.tsx:299-305`).
- Canvas drag/resize: `canvasDragOperation`/`canvasResizeOperation` return
  `null` when `!isNodeDirectGeometryEditable(...)`
  (`canvasOperations.ts:41,77`) — so dragging a layout-managed node produces no
  op (the gesture is a no-op).
- Arrow-key nudge is blocked for layout-managed/locked nodes
  (`EditorApp.tsx:662`).
- Direct geometry edits are ALSO clamped to parent bounds
  (`clampNodeTransformToParentBounds`, `clampNodeSizeToParentBounds`,
  `sceneQueries.ts:194-228`) and snapped to guides (`canvasOperations.ts`
  snap fns). So even free nodes can't leave the parent box.

This is exactly the user's stated prior-attempt failure: positions are SOLVED,
the UI hard-disables direct geometry whenever the solver owns the node, and
even for free nodes geometry is clamped to the parent.

---

## 4. How the editor gets & keeps the scene in sync

- Initial scene is `initialScene` prop → `useState<Scene>` (`EditorApp.tsx:173`).
- On WASM activation, `new WasmEngine(module, sceneRef.current)` constructs the
  engine, which relays out on load; `setScene(engineRef.current.scene)` adopts
  the relaid scene as the render source (`EditorApp.tsx:288-294`).
- Per-edit: `setScene(result.scene)` where `result.scene` is the delta-merged
  snapshot (`EditorApp.tsx:431`, `wasmEngine.ts:268-271`). React re-renders the
  canvas + inspector from this immutable, structurally-shared `Scene`.
- Out-of-band scene replacement (agent drafts, preflight, undo/redo, reconcile)
  goes through `replaceScene` (`EditorApp.tsx:321-334`): it calls
  `engine.reset(nextScene)` (re-lays-out in wasm) then `setScene(engine.scene)`
  so geometry stays single-source and text doesn't jump.
- `refreshSceneFromEngine` (`EditorApp.tsx:340-345`): the CanvasKit canvas
  installs SkParagraph text measurements straight onto the engine
  (`WasmEngine.setMeasurements`, `wasmEngine.ts:235-238`), which relays out
  WITHOUT emitting a delta, then the React scene is re-synced from
  `engine.scene`. This is the "measure-then-inject" text-honesty path
  (Decision E3/C4).
- Rendering: `renderAdapter.ts` turns each `Node` into a `RenderNodeDescriptor`,
  preferring `node.computed.layout_bounds` for size/position and falling back to
  `transform`/`size` only when `computed` is absent
  (`renderAdapter.ts:476-517`). For a layout-managed node with no computed it
  renders at parent origin (0,0), NOT at `transform`, because transform is not
  its real position under flow (`renderAdapter.ts:505-512`).

---

## 5. Undo/redo: two independent systems

1. **Local optimistic undo (client snapshot stack).** `applyOperations` pushes
   `{ scene: previousScene, operations }` (`EditorApp.tsx:421-427`).
   `undoLastOperation`/`redoLastOperation` (`EditorApp.tsx:556-607`) simply
   `replaceScene(frame.scene)` — i.e. they restore a whole prior scene snapshot
   and re-lay-out, NOT by applying inverse operations. Capped at 50 frames.
   Bound to Ctrl/Cmd-Z / -Shift-Z and toolbar buttons (`EditorApp.tsx:640-643,
   1182-1186`).
2. **Server committed history.** `HistoryPanel` calls `undoDocument`/
   `redoDocument` against `/documents/{id}/undo|redo` (`structuredEdits.ts:216-222`)
   and renders persisted envelopes with `inverse_operations` and `invertible`
   flags (`structuredEdits.ts:176-199`, `HistoryPanel.tsx`). This is the durable,
   inverse-op-based authority. The engine also RETURNS `inverse_operations` per
   apply (`wasmEngine.ts:273`) but the local stack does not currently use them
   (it snapshots scenes instead).

Note the two are not coordinated: the local stack is scene snapshots; the server
stack is inverse operations. After a reconcile/divergence the local stack is
stale relative to the server.

---

## 6. Crop & opacity, concretely

- **Opacity: EXISTS.** Number field 0–1 in the inspector (`InspectorPanel.tsx:
  281-297`), plus an opacity-token select when brandTokens are present
  (`559-573`). Patched via `nodePatch({ opacity: set(...) })` /
  `opacity_token`. `renderAdapter` passes `opacity: node.opacity` to the
  descriptor (`renderAdapter.ts:177`).
- **Crop: DOES NOT EXIST in the UI.** The data model supports it
  (`asset_placement.fit = "crop"`, `focal_point`, `clip` boolean — see §2
  ABSENT), and operations can carry it (`operations.ts:57-58`), but there is no
  inspector control, no canvas crop handle, and no image inspector section. A
  human cannot crop an image or clip a shape through the editor today; only the
  agent / raw scene authoring can set those fields.

---

## 7. Editing implications & round-trip

### What works today for "basic-editor" human editing
- Free (non-layout-managed, unlocked) top-level nodes: drag, resize, rotate via
  canvas; X/Y/W/H/rotate via inspector; opacity, fill/stroke color, stroke
  width, corner radius, and full text typography all editable. This is a
  workable basic editor FOR FREE NODES.
- Color/opacity/typography editing works regardless of layout management
  (they're not geometry) — gated only by `locked`.

### Where it fights the solver (the user's core problem)
- The instant a node is an auto-layout child, ALL direct geometry editing is
  hard-disabled in both the inspector (`disabled={!directGeometryEditable}`) and
  the canvas (`canvas*Operation` returns null). There is no FREEHAND escape
  hatch: no "detach from layout / make absolute" toggle anywhere in the UI.
- Even free nodes are clamped to parent bounds and guide-snapped, so a node
  cannot be dragged outside its parent. There is no reparent-by-drag; only
  same-parent reorder via LayerPanel arrows.
- `transform` on a layout-managed node is NOT its rendered position (flow owns
  it); `renderAdapter` even renders such a node at parent origin when `computed`
  is missing (`renderAdapter.ts:505-512`). So "store the dragged position in
  transform" would be ignored by the solver — exactly why the prior attempt
  failed.

### Implications for a FREEHAND mode (proposal 1)
- The data model already distinguishes managed vs free: a node is layout-managed
  iff its parent is `auto_layout` (`sceneQueries.ts:172-181`), and `transform`
  is honored as authored position for non-managed nodes
  (`renderAdapter.ts:513-516`). So "freehand" could mean: ensure the dragged
  node's parent is NOT an auto-layout container (e.g. detach to a `frame`/`group`
  or to the page, preserving its computed absolute position into `transform`).
- The op vocabulary needed mostly exists: `updateNodeLayout(node, null)` to
  clear a container's auto-layout (`operations.ts:305-313`),
  `moveNodeToParent` to reparent (`operations.ts:356-363`),
  `updateNodeTransformAndSize` to pin absolute geometry
  (`operations.ts:294-303`). MISSING: any UI/command that (a) reads the node's
  current `computed` bounds, (b) reparents it out of the auto-layout flow, and
  (c) writes those bounds into `transform` + fixed `size` atomically. Also
  MISSING: a per-node or per-container "freehand" toggle and the
  `editorModes.ts` only enumerates PANEL modes (inspector/agent/export/
  diagnostics, `editorModes.ts:1-15`), NOT a canvas freehand/layout edit mode.
- Clamping (`clampNodeTransformToParentBounds`) would need relaxing in freehand
  mode, else freely-moved nodes still snap back inside the parent box.

### Implications for LAYOUT-MANAGED editing (proposal 2)
- Already partly real: sizing-mode, gap, padding, align, grow, and token edits
  all flow through `updateNodeLayout`/`updateAutoLayoutNode` and re-lay-out in
  wasm. The "edit while the solver governs layout" mode largely exists for those
  properties. What's missing is geometry-as-intent (e.g. drag to change order /
  alignment / gap rather than absolute x/y) — the gesture layer currently maps
  drag only to absolute transform, which is then refused for managed nodes.

### Round-trip (the hard question): can the AGENT take back a human freehand edit?
- Authoritative state is the `Scene` (nodes with `transform`, `size`, `layout`,
  parent membership via `children` arrays). Both the human edit path and the
  agent operate on the SAME scene through the SAME `Operation`/wasm engine, and
  edits are persisted to `/documents/{id}/operations` with full history +
  `inverse_operations` (`structuredEdits.ts:176-199`). So mechanically, a
  human's freehand edit is just more operations producing a new authoritative
  scene the agent can later read and re-edit. There is no separate
  "human-only" representation that the agent cannot see — this is the key
  enabler for round-trip.
- The HARD part is SEMANTIC, not mechanical: today a freehand edit that
  reparents a node and switches it relative→absolute would leave a node whose
  `transform` is now meaningful (free) where the agent's authoring model assumes
  layout-managed flow. The agent runtime authors in lumen-DSL and runs an
  author→preflight→repair loop; if it regenerates the subtree it will likely
  clobber the human's absolute placement (the DSL/relayout owns position). There
  is NO marker in the model today distinguishing "agent-owned, safe to relayout"
  from "human-pinned, preserve absolute position." (Speculation: a per-node flag
  like `pinned`/`authored_by` or an "absolute" positioning kind would be needed
  so the agent's repair loop preserves human freehand intent; none exists today.)
- `locked` is the closest existing primitive (`Node.locked`,
  `contracts.ts:180`) — it blocks human and op-level geometry edits — but it is
  not consulted by the agent runtime as a "do not relayout" signal, and locking
  also blocks the human, so it is not a freehand-preservation mechanism.

### Concrete gaps to build (labeled)
1. A freehand/layout edit MODE concept in the editor (today `editorModes.ts` has
   only right-panel modes). — MISSING.
2. A "detach to absolute" command: read `computed` bounds → reparent out of
   auto-layout → write transform+fixed size atomically. Ops exist; the
   orchestration does not. — MISSING.
3. Crop / image-fit / focal-point / `clip` UI (model + ops exist). — MISSING.
4. Reparent-by-drag and cross-parent moves on canvas (only `moveNodeToParent`
   exists as an op; only LayerPanel same-parent reorder uses it). — MISSING.
5. A persisted "human-pinned / positioning intent" signal so the agent repair
   loop can preserve freehand edits across re-authoring. — MISSING (the crux of
   round-trip).
6. Gradient/effect inspector editing (color picker downgrades gradients to
   solid). — MISSING.

### What EXISTS today and is reusable
- Single converged `Operation` pipeline with optimistic wasm apply + delta merge
  + server reconcile (`applyOperations`, `wasmEngine`, `editQueue`).
- Full op vocabulary including `update_node` (transform/size/layout/clip/
  asset_placement/opacity), `move_node`, `insert_node`, `remove_node`
  (`operations.ts`).
- Managed-vs-free classification and direct-geometry gating
  (`sceneQueries.ts`).
- Server history with inverse operations + checkpoints
  (`structuredEdits.ts:176-238`).
- Structured-edit format and `WasmEngine.applyStructuredEdit` (unused by UI but
  available) — a natural channel for higher-level human/agent intents.
