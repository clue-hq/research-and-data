# Phase 1c — Invertible freehand operations

Date: 2026-07-03 · Branch: `agents/editing-roundtrip-v0`
Plan: `.context/editing-research/PHASE-1-PLAN.md` §1c
Commit: `1ffd338` (code), records follow.

Three named, invertible operations wrap the raw freehand patches that 1b's
browser run validated end-to-end. They ride the shared
`StructuredEditInstruction` → `build_structured_edit_batch` seam (editing.rs),
so **the API helper and the browser WASM gained them with zero binding
changes** — verified live by driving the real wasm bundle's
`applyStructuredEdit` in Node (detach → pinned at the solved box, 1 inverse
op attached; reattach → managed, box cleared, re-flowed into the stack).

## The three operations

- **`detach_to_freehand {node_id}`** — pins the node at its *solved* box:
  `absolute_box = base_anchor = computed.layout_bounds`. The detached node
  itself does not move; flow siblings close the vacated slot on the next
  solve (Figma's absolute-position semantics — freezing a whole section in
  place is what container conversion is for). Hug/Fill dimensions bake to
  Fixed at the solved extent so the size spec matches what the human sees
  and survives a later re-attach. **Fixed keeps its authored value; Token
  keeps its binding** — baking a token to a number would silently sever
  brand governance.
- **`reattach_to_layout {node_id}`** — `position_mode` back to Managed,
  pin + anchor cleared; the next solve re-flows the node. The size baked at
  detach (or resized since) is kept: the solver cannot know what Hug/Fill
  meant before the human took over.
- **`convert_container_layout {node_id, layout_mode: stack|free}`** — flips
  a container between the flex solve and hand-placed children. **To Free is
  zero-motion by construction**: every managed child's transform bakes to
  its solved offset inside the container and Hug/Fill bake to Fixed
  (geometry maps assert byte-equal before/after). Children already pinned
  Absolute are skipped — their page-space box keeps winning either way. To
  Stack only flips the mode; the solve re-stacks children in tree order,
  which is the point of re-managing.

Guardrails on every builder: `LockedTarget`, `TargetNotFound`,
`UnsupportedTarget` (already-freehand / not-freehand / not-a-container /
no-op mode), and a computed-geometry precondition (`OperationFailed`,
"run layout before …") — the builders never solve internally, so they can
never disagree with the canonical measurer.

**Exact inverses** via `with_inverses` on every batch (the UpdateNode
inverse arm 1a extended): tests assert applying `inverse_operations`
restores the pre-edit scene **byte-identically**. This is the machinery 0c's
Accept/Reject uses and the future Compare/Revert will reuse.

Editor side: `structuredEdits.ts` gained the three wire-format helpers
(`detachToFreehandEdit` / `reattachToLayoutEdit` /
`convertContainerLayoutEdit`) — 1d's UI calls these into
`WasmEngine.applyStructuredEdit`, which already routes through the same
lumen-core builder as the server.

## Gates (all green)

- **10 new tests** (`tests/freehand_ops.rs`), driven through the **wire
  format** (serde JSON in, pinning the tags the bindings send): detach
  pins/bakes/inverts byte-identically; computed-geometry precondition;
  locked/missing/double-detach errors; reattach returns the node to its
  stacking slot and keeps the baked size; convert-to-free zero-motion +
  byte-identical inverse; convert-back re-stacks hand-moved children;
  pinned children skipped (no op emitted for them, pin survives);
  non-container/no-op-mode errors; wire kinds pinned
  (`detach_to_freehand`, `reattach_to_layout`, `convert_container_layout`,
  `layout_mode: "free"`).
- Rust workspace **509 passed, 0 failed** (499 + 10 new; lumen-assets
  `providers_contract` still pre-broken at HEAD, unrelated).
- Python **186 passed, 4 skipped** (uv env, `--with pillow`).
- Editor **351/352** (the known env-split test) + typecheck clean apart
  from the pre-existing `ExportPanel.test.tsx` error.
- Real-wasm binding round-trip in Node (above).

## The Moda clip clarification (user FYI, screenshots in `moda-reference/`)

Two reference screenshots settle how Moda treats masking, shared before 1c
started:

1. `moda-image-overlaps-card-unclipped.png` — an image overlapping a
   rounded card renders **in full**; grouping does not mask. Containers/
   groups are organizational, not clipping.
2. `moda-image-past-page-edge-clipped.png` — the same image dragged past
   the page edge **is clipped at the page boundary** (selection handles
   extend beyond; pixels stop).

Mapping to us: **our editor already matches** — CanvasKit clips at the page
boundary only (`CanvasKitStage.tsx:169`; proven in 1b's screenshots), and
node-level `clip:true` is not painted in-editor. The 1b flag "editor lacks
node-level clip painting" is hereby **reframed: that behavior is Moda
parity, not a gap**. The remaining divergence is the **export path**
(server Skia honors `clip:true` on interior cards, `render.rs:215`) — a
freehand node dragged across a clipping card shows fully in-editor but
would clip on export.

**Decision teed up for 1d (recommendation):** adopt Moda's semantic at
render time — a freehand (Absolute) node escapes its ancestors' masks and
is clipped **only by the page**, in the export renderer too. That makes
editor and export agree without adding node-clip painting to the canvas,
and reads naturally: `position_mode: absolute` = out of the parent's
layout *and* out of its mask; the parent link stays organizational (the
node stays in `children`, exactly like Moda groups). Managed content keeps
clip semantics everywhere — agent-authored cards still mask their own
managed children. Alternative (paint node clips in-editor for strict
current-export WYSIWYG) would make us *more* aggressive than Moda and
makes content vanish mid-drag; not recommended.

## Next: 1d — editor unlock + gestures (finishes Milestone M1)

Open `isNodeDirectGeometryEditable` (sceneQueries.ts:183) for Absolute
nodes and Free-container children; point drag/resize commits at
`absolute_box`; "Detach to freehand" / "Re-attach" selection actions
calling the 1c helpers; inspector X/Y/W/H live for pinned nodes; the
render-clip decision above; CanvasKit browser e2e (planned to run on an
Opus 4.8 subagent, per user). Pinned-text LUMV0902-4 resize policy also
lands there.
