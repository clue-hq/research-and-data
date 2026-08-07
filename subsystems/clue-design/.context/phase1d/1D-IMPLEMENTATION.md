# Phase 1d — Freehand editor unlock + gestures + render policy

Date: 2026-07-03 · Branch: `agents/editing-roundtrip-v0`
Plan: `.context/editing-research/PHASE-1-PLAN.md` §1d · Commit: `af87f44`
(code); records follow. **Finishes the interaction side of Milestone M1**
("Moda-basic": a human drags/resizes an auto-layout child and it sticks).

## What shipped

### Render policy — freehand escapes masks, everywhere (from the user's Moda screenshots)

The decision teed up in 1c, implemented across every surface: a **pinned
node escapes its ancestors' masks and paints in a page-level pass above
in-flow content** (document order); only the page clips it. A pinned node
still masks its *own* managed children when it clips. One shared
definition in `render_geometry.rs` (`paints_out_of_tree`,
`pinned_paint_pass`), consumed identically by:

- **Skia rasterizer** (`lumen-skia/render.rs`) — pixels prove it: a pinned
  child of a clipping card paints fully outside the card, above a
  green rect that comes later in tree order, while a managed sibling's
  overflow stays clipped (`freehand_render.rs`).
- **SVG exporter** (`lumen-export/svg.rs`) — pinned markup emitted after
  all in-flow content, outside clip groups (markup-order test).
- **Vector PDF** (`lumen-export/pdf.rs`) — stacking parity (it never
  implemented masks, so only paint order needed the mirror).
- **Editor CanvasKit stage** — the descriptor build hoists pinned subtrees
  to a page-level top layer, so editor z == export z.
- **`hit_test.rs`** — the same two-pass, so clicking where a pinned node
  overlaps in-flow content selects what renders on top.

Scope note (recorded deliberately): only **pinned (Absolute)** nodes
escape masks. Children of a Free container stay inside their container's
paint (and its clip, if set — surfaced by the LUMV0801 warning). The
critical Moda case — drag a thing out of a card and see it whole — always
goes through detach, which pins.

### Editor gestures (the second half of the recording's mechanism story)

- **Gate**: `isNodeDirectGeometryEditable` opens for pinned nodes and
  Free-container children (`isNodePinned` / `isNodeFreehand`, mirroring
  the Rust `is_freehand`). The "Layout-managed child · handles Disabled"
  verdict no longer misclassifies freehand nodes.
- **Pinned drags commit to `absolute_box`** (page space) — fixing the
  second snap-back layer found while explaining the recording: the old
  commit wrote `transform`, which pinned nodes ignore. **No parent-bounds
  clamp** for freehand commits (the clamp was the "fights your hand"
  behavior rejected with clip-policy option b); no guide snapping on
  pinned drags in v1 (fast-follow candidate). Resizes rewrite the box and
  bake the Fixed size in one patch (the detach invariant); rotation rides
  the transform.
- **Free-container child drags** commit parent-relative transforms
  (via `parentComputedOrigin`), unclamped.
- **Parent drag carries pins**: dragging a container emits one
  `absolute_box` translation per pinned descendant — same committed
  (possibly guide-snapped) delta, one atomic batch, one undo frame.
  Solver/agent reflows still never move a pin; only the explicit human
  gesture does. The canvas commit chain became batch-based
  (`onOperations`) end to end; the legacy Konva surface wraps singles.
- **Inspector**: "Detach" / "Re-attach" header actions call the 1c
  structured edits through `engine.applyStructuredEdit`, committed by
  `EditorApp.applyStructuredEditInstruction` with the exact bookkeeping
  manual edits get (undo frame, history, persistence). X/Y/W/H read and
  write the pinned box live; state label reads "Pinned (freehand)".
- **Contracts**: TS `Node`/`NodePatch`/`AutoLayoutProps` carry the
  freehand fields; `nodePatch` skips-when-unchanged and
  `nodePatchAffectsRender` mirrors the Rust arm (the 1a deferred item).

### Pinned-text policy (the deferred 1b decision, resolved)

LUMV0902/0903/0904 (text fit) downgrade to **warnings for freehand
nodes** — resizing a pinned text box below its content is explicit
intent and the canvas shows the truncation; managed text keeps the
fail-closed errors protecting agent-authored copy. Same shape as the
1b LUMV0800/0801 policy, same `is_freehand` source.

## Gates

- Rust workspace **512 passed, 0 failed** (2 new render-policy tests,
  1 new text-policy test; hit-test suite green under the two-pass).
- Editor **358/359** — 7 new freehand gesture tests (gate opens for
  pinned + Free-child; pinned drag → box, unclamped, transform untouched,
  computed cleared; resize bakes Fixed size; container drag emits pin
  translations following the snapped delta; zero-delta drags emit no
  translations; free-child commits parent-relative). The 1 failure is
  the known pre-existing CanvasKit-default env-split test.
- Python **186 passed**. Helper/wasm handshake verified at `af87f44`.
- Pre-existing and unchanged: `lumen-assets` `providers_contract`
  compile break; `ExportPanel.test.tsx` tsc error.

## Browser e2e (CanvasKit, real editor + real engine — run by an Opus 4.8 subagent)

**ALL 7 STEPS PASS** — full report + screenshots in `browser-e2e/`.
The headline sequence, each step asserted against engine truth AND the
live render: UI **Detach** (zero-motion pin, sibling closes the slot,
inspector goes live) → **pinned canvas drag sticks** (box rewritten,
`base_anchor` preserved) → **drag past the page edge honored, fill
render-clipped at the artboard boundary** (the user's Moda reference
behavior, now ours) → **parent drag carries the pin by the exact
committed delta** (0.0mm divergence, guide-snap included) →
**Re-attach re-flows** into the stack slot → **two undos** unwind
re-attach then the whole parent-drag batch atomically (one frame for
container + pin carry). Harness findings for future runs (synthetic
pointer events must target the canvaskit-interaction-layer; the
selection overlay is graphics-only) are recorded in the report.

## Deferred / fast-follows (recorded)

- Guide snapping for pinned drags (kept off in v1 to keep the hand in
  control; Moda-style smart guides are polish).
- Auto-detach-on-drag (locked decision: explicit toggle first).
- Container Free/Stack conversion UI (the 1c op + wire helpers exist;
  agent/API can call it today).
- Reparent-on-drag (frame adoption), multi-select transform — still
  explicitly out of Phase 1 per STUDY §Deferred.
- Konva test surface keeps single-op commits (no pin translation) —
  it is not the product surface.

## Next: 1e — agent visibility

Expose `position_mode` / `absolute_box` / `base_anchor` / container
`layout_mode` in `_node_brief` / `summarize_scene` (tools.py) + a prompt
note (respect pinned boxes; use `base_anchor` to preserve offsets), so
the agent sees "human pinned this" — closes the deferred Phase-0 item 4
and completes Phase 1.
