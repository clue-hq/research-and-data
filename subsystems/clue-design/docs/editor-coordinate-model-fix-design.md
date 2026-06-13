# Editor Coordinate-Model Fix — Critical Design

Date: 2026-06-13
Branch: `editor/coordinate-model-v0` (cut from `main` `154bc41`)
Status: design; no code yet.

## The bug, restated precisely

Dragging an element in the editor can drag other elements with it "at the same
distance, anchored," and nested content desyncs after the move. Root cause,
traced through the live code on `main`:

The editor keeps **two disagreeing position sources**:

- **Render** (`renderAdapter.nodePositionForRender`) reads
  `node.computed.layout_bounds` (absolute, produced by a layout pass) whenever
  it exists, falling back to `node.transform` only when `computed` is absent.
- **Edit** (`canvasOperations.canvasDragOperation`) commits
  `UpdateNode{transform}`. In `lumen-core`/the wasm engine, a render-affecting
  patch **clears `computed` on the touched node only** (operations.rs:65 —
  `nodePatchAffectsRender(patch) ? clear() : unchanged()`), and
  `LumenEngine.apply_operations` (wasm `engine.rs`) **does not re-run layout**.
  `EditorApp.applyOperations` then `setScene(result.scene)` — a scene whose
  `computed` tree is now half-cleared.

`SceneNode.tsx` renders children as **nested Konva `<Group>`s** and derives each
child's `parentComputedOrigin` from the parent's `computed`. So after a
container drag: the parent renders from its new `transform` (its `computed` was
cleared → `parentComputedOrigin` becomes `null`), while the children still hold
stale absolute `computed` — they translate by the parent's delta (Konva
nesting) **and** land at the wrong relative offset (the parent-origin
subtraction broke). Hence "anchored, same distance, and shifted."

**The bug is broader than drag.** Any render-affecting edit clears `computed` —
including a fill or opacity change. For a node whose position is owned by layout
(an auto-layout child, a hug-sized container), falling back to `transform` is
*wrong* (its transform is not its real position), so a non-geometry edit can
also make a node jump. The drag case is just the most visible instance.

It is **not** a Konva bug (Konva does what it's told) and **not** a core/engine
bug (`UpdateNode{transform}` is correct; the server's next preflight/layout
reconciles everything — which is why it sometimes self-heals on round-trip). It
is an **editor coordinate-model inconsistency**: the render path and the edit
path disagree about what "position" means, and `computed` is allowed to go
stale/partial before render.

## Design principle

**`computed` geometry is a derived cache the editor must always keep fresh.**
The editor renders from `computed` and nothing else; after any mutation,
`computed` is recomputed for the whole tree by a single layout pass, so parent
and children are always laid out together and can never disagree. `transform`
(and size, auto-layout props, …) are *inputs* to layout, never a second render
source.

This is renderer-agnostic — it lives in the shared engine + render-adapter
layer, so the future CanvasKit canvas inherits one clean model instead of
re-deriving Konva's accidental nesting behavior by hand. It is therefore the
natural **slice 0 of Wave 3 (CanvasKit)**, done now against the live Konva
editor so the bug is fixed today and the model is ready for the swap.

## Part 1 — Engine-backed geometry reconciliation

### What changes

1. **The wasm engine refreshes `computed` after every mutation and on load.**
   Add `LumenEngine::relayout()` that runs the existing
   `layout_operations(&self.scene)` (which produces `UpdateNode{computed}`
   geometry ops) and applies them to `self.scene`, leaving the whole tree's
   `computed` fresh and mutually consistent. `apply_operations` /
   `apply_structured_edit` / `compile_dsl_block` call `relayout()` as their
   final step; `from_scene_json` / `load_scene` call it once so the editor
   starts from a coherent baseline. Expose `relayout()` (and have the apply
   methods return the relaid-out scene/delta).

2. **`computed` is refreshed for RENDER only — never persisted to the server.**
   The operations the editor sends to `/edits` remain the authored edits
   (transform/size/fill/…). The local `relayout()` updates `computed` purely
   for the optimistic local render. The server runs its own canonical
   preflight/layout (Skia) and owns the authoritative geometry for
   export/fit/preflight. We must **not** ship heuristic `computed` values into
   operation history.

3. **The editor renders exclusively from local (always-fresh) `computed`.**
   `nodePositionForRender` keeps preferring `computed`; after this change
   `computed` is effectively always present and whole-tree-consistent, so the
   parent/child desync cannot occur. The `transform` fallback stays only as a
   guard for a node that has never been laid out, and is made layout-safe (see
   Risks).

### Critical analysis (why this is correct, and the traps avoided)

- **Layout honors the drag.** `layout.rs` positions non-auto-layout children at
  `origin + child.transform` (lines 183–184, 348–349, 363). So after a drag
  updates `transform`, `relayout()` yields `computed = parent_origin +
  new_transform` for the node *and* recomputes its descendants under the new
  origin — the whole subtree is coherent. Auto-layout children are repositioned
  by flow (already correct, and they are non-draggable).

- **Heuristic-vs-Skia divergence is made consistent, not introduced.** In-browser
  layout uses the heuristic measurer (skia-safe can't target wasm32 — Decision
  E3). If we naïvely re-laid out a server-Skia-measured scene, text nodes would
  shift to heuristic positions on the first edit. The fix avoids this by being
  **idempotent within the editor session**: `relayout()` runs once on load, so
  every node (including text) is already at its heuristic position before any
  edit; subsequent `relayout()`s leave unrelated nodes unchanged
  (`heuristic(heuristic_scene)` is a fixed point). So dragging a rect does
  **not** nudge nearby text — only the dragged node and its true
  layout-dependents move. The accepted cost is a small, *constant* heuristic-vs-
  export offset for text, which is the already-documented E3 caveat and which
  **Wave 3 erases** (CanvasKit brings SkParagraph in-browser, so local
  measurement becomes Skia and converges with the server).

- **Server reconcile must not re-introduce jumps.** The W3 optimistic pipeline
  round-trips authored ops to `/edits` and reconciles on response. The server's
  scene carries Skia `computed`. To keep the editor jump-free, **reconcile on
  the authored fields and re-derive `computed` locally** (run `relayout()` on
  the reconciled authored scene) rather than rendering the server's Skia
  `computed` directly. Editor render geometry thus stays single-source (local
  heuristic), and the server geometry is used for export/preflight/fit, which is
  exactly where Skia honesty matters.

- **Performance is a non-issue.** Layout over editor-scale scenes (tens to low
  hundreds of nodes) with heuristic measurement is sub-millisecond in wasm. A
  relayout per edit is free.

- **Undo/redo and history are unaffected.** Local undo frames are scene
  snapshots; they capture the relaid-out `computed` and restore coherently.
  Inverses/envelopes operate on authored fields; derived `computed` is never in
  the operation payload.

- **Flag-gating.** This fix uses the in-browser engine, which lives behind
  `NEXT_PUBLIC_LUMEN_WASM_CORE`. With the flag **on** (the path we are moving
  to), the fix is complete. With the flag **off** (legacy TS path, being
  retired), there is no local engine to relayout; the legacy path keeps its
  current behavior and reconciles only on the server round-trip. This is an
  additional, concrete reason to make the wasm core the default. Documented, not
  worked around.

## Part 2 — Container-drag semantics (renderer-agnostic UX)

Moving a frame **should** move its contents — that is correct and stays. The
defect is that the user cannot tell they grabbed a container and has no
deliberate way to target the child. Three additions, none renderer-specific:

1. **Selection clarity for containers.** When the selected node is a container
   (`frame`/`group`/`auto_layout` with children), render distinct selection
   chrome — a labeled bounding box (e.g. the node name) and faint outlines of
   its direct children — so "I selected a container holding N elements" is
   visible before any drag.

2. **Deliberate child targeting.**
   - **Layer panel** already lists the nested tree with depth indentation and
     `onSelectNode` (`LayerPanel.tsx`); clicking a nested row selects that child
     regardless of canvas overlap. Make this the discoverable primary path
     (and reflect canvas selection back into the panel).
   - **Double-click to enter a container** (Figma model): a single click selects
     the outermost container under the cursor; double-click "enters" it and
     selects the deepest child under the cursor; `Esc` steps back out. Track an
     "editing context" (which container you are inside) so subsequent
     clicks/drags target within it.
   - **Modifier click-through**: `Cmd`/`Ctrl`-click selects the deepest node
     under the cursor directly.
   (Note: the current `onClick` uses `cancelBubble`, so a click already selects
   the deepest node; the gap is specifically grabbing a container's *background*
   to drag it, which the clarity + entry model makes intentional.)

3. **Keep container-moves-children.** No "lock children" mode in V0; the goal is
   comprehension and precise targeting, not changing the (correct) semantics.

## Slices

- **CM0 — failing tests + repro fixture.** A scene fixture mirroring the agent's
  output (a `hero` frame containing headline/body/logo, plus a sibling), with
  tests asserting: after dragging the frame, every child's *rendered* position
  equals `relayout`'s computed (no stale-offset desync); after a fill edit on a
  layout-positioned node, its position is unchanged. These fail today.

- **CM1 — engine relayout.** `LumenEngine::relayout()` in `lumen-wasm`;
  `apply_operations`/`apply_structured_edit`/`compile_dsl_block`/load paths end
  with it; the returned scene/delta carries whole-tree-fresh `computed`. Rust
  tests: relayout is idempotent on an already-laid-out scene; a transform edit
  updates the node's and descendants' `computed` consistently; computed ops are
  not in the returned *operations* (server payload), only in the scene.

- **CM2 — editor render single-source.** `EditorApp`/`wasmEngine.ts` consume the
  relaid-out scene; `relayout` on load and after each edit; reconcile re-derives
  `computed` locally from the server's authored scene (no Skia-computed render
  swap). The render adapter is unchanged except the `transform` fallback is made
  layout-safe. Vitest: the CM0 repro passes; the gesture-conformance envelope
  output is unchanged (authored ops identical — we changed render, not edits).

- **CM3 — container selection clarity.** Distinct container selection chrome +
  child outlines; canvas↔layer-panel selection sync. Component tests.

- **CM4 — child targeting.** Double-click-to-enter (+ `Esc`), modifier
  click-through, layer-panel-driven selection. Interaction tests for each path;
  a container drag still moves children (semantics preserved).

- **CM5 — conformance + Wave-3 handoff.** Full matrix; a note in the Wave 3 plan
  marking this as the delivered C-slice-0 (CanvasKit builds hit-testing/drag on
  this single-source model). Manual interaction QA recorded.

## Risks

| Risk | Mitigation |
|---|---|
| Re-layout perturbs unrelated text (heuristic) | relayout-on-load makes it idempotent; only true layout-dependents move (CM1 idempotence test) |
| Server Skia `computed` swap causes reconcile jumps | reconcile on authored fields, re-derive `computed` locally (CM2) |
| Heuristic `computed` leaking into history | relayout updates the scene's `computed` for render only; operation payload stays authored (CM1 test asserts) |
| `transform` fallback mis-positions a never-laid-out layout-managed node | make the fallback layout-safe: for a layout-managed node with no `computed`, render at parent origin / 0 rather than a meaningless transform, and ensure load-relayout removes the case |
| Fix only active with the wasm-core flag on | documented; reinforces defaulting the flag; legacy path keeps current reconcile-on-server behavior |
| Container UX scope creep | V0 = clarity + targeting only; semantics unchanged; no lock-children/isolation modes |

## Acceptance criteria

- Dragging a container moves its children and, after the move, every node's
  rendered position equals a single coherent layout pass — no stale-offset
  desync, no anchored-and-shifted children.
- A non-geometry edit (fill/opacity) on a layout-positioned node does not move
  it.
- Authored operations / persisted envelopes are byte-identical to before
  (render changed, edits did not) — gesture-conformance suite still green.
- The user can see when a container is selected and can deliberately target a
  child (layer panel, double-click-enter, modifier click).
- Full matrix green; the design is recorded as Wave 3's C-slice-0.
