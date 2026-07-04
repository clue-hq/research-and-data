# Phase 1b — Solver honors the freehand fields (+ decided clip policy)

Date: 2026-07-03 · Branch: `agents/editing-roundtrip-v0`
Plan: `.context/editing-research/PHASE-1-PLAN.md` §1b · Design: STUDY.md §3

**The increment where a detached node stops snapping back.** The solver now
honors `position_mode: absolute` + `absolute_box` (Stance A spine) and
`layout_mode: free` containers (Stance C graft), and the user-decided clip
policy (option a, 2026-07-03) downgrades LUMV0800/LUMV0801 to warnings for
freehand nodes only.

## What changed (all in `crates/lumen-core/src/layout.rs`)

1. **Out-of-flow widen** (`build_taffy_node`): an `Absolute` child is skipped
   from the taffy flex tree exactly like a rotated child — but *silently*
   (no LUMV0701: rotation is accidental out-of-flow, a pin is deliberate).
   `flow_context` likewise excludes Absolute children from fill/space math,
   so a Fill sibling reclaims the detached child's slot.
2. **Absolute nodes lay out at `absolute_box`** (`layout_node_at`): the box
   is authoritative for **both position and size** (`layout_bounds ==
   absolute_box`, byte-exact). For an Absolute *auto-layout container*, the
   box is forced as the root style of its own taffy solve (`style_for_node`)
   and the exact f64 box is written back in `collect_taffy_geometry`
   (taffy solves in f32), so children keep composing *inside* the pinned
   box. Invariant that keeps this simple: a pinned node only ever enters a
   flex solve as its root — children of a solve are never Absolute.
   `Absolute` without a box falls back to flow position (mirrors the
   rotated-child treatment).
3. **Free containers** (`layout_node_at` kind-switch + a leaf branch in
   `build_taffy_node`): a `layout_mode: free` container skips the flex solve
   — children lay out at their own baked transforms (container origin +
   `transform.x/y`), while the container itself still participates in its
   parent's flow as a plain box. Nested Free-in-Stack works through the
   existing `collect_taffy_geometry` fallback loop with zero extra code.
4. **Clip policy — decided option (a)** (`validate_node_against_page`,
   `validate_node_children_against_parent`): a *freehand* node (Absolute, or
   child of a Free container — `is_freehand`) that exceeds its clipping
   parent (LUMV0801) or the artboard (LUMV0800) now gets a **Warning** with
   a freehand-specific hint instead of an Error. Managed content keeps
   today's fail-closed errors — the agent's own designs stay as protected
   as before. Slot-subject LUMV0800/0801 (different concern, Slot subjects)
   untouched.

Render needed **zero changes**, as predicted: `computed` fills from the box
and every renderer reads `computed`.

## Gates (all green)

- **12 new tests** `crates/lumen-core/tests/freehand_layout.rs`: pin lands
  exactly at box + siblings reflow; no snap-back across computed write-back
  relayouts (the editor's cycle); pinned auto container solves children
  inside the box (authored size 999×999 loses to the box — box wins);
  Free container children at baked transforms; Free-in-Stack flows as a box;
  fill math excludes pinned children; Absolute-without-box falls back to
  flow; pinned box wins over Hug for text; LUMV0801 warning-for-freehand vs
  error-for-managed in one scene; same for LUMV0800; Free-container child
  overflow warns despite `clip=true`; a freehand drag past a clipped parent
  **lands through `apply_operations_checked`** and produces zero
  error-severity layout diagnostics (the acceptance gate stays open).
- **Rust workspace: 499 passed, 0 failed** (was 487 + 12 new) — includes W6
  conformance/parity, visual-regression goldens, wasm-helper parity.
  `lumen-assets` `providers_contract` still pre-broken at HEAD (missing
  image-work fields, unrelated); its other targets pass (3+6+6+9).
- **Python: 186 passed, 4 skipped** through the helper built from this tree
  (`uv run --with-requirements apps/api/requirements-dev.txt --with pillow`;
  the 3 image tests need Pillow, which requirements-dev.txt omits — env
  quirk, not code). The 0b untouched-nodes byte-identity fixtures act as the
  live parity gate: solver output for pre-freehand scenes is unchanged.
- **Editor: 351/352** with the 1b wasm bundle — identical to the 1a
  baseline (the 1 is the known CanvasKit-default env-split test). Suite runs
  with `NEXT_PUBLIC_LUMEN_CANVASKIT=0` (jsdom can't load canvaskit.wasm; at
  default flags 27 tests fail identically at clean HEAD — verified
  pre-existing, environmental). Pre-existing lint error in
  `ExportPanel.test.tsx` (TS2493) also confirmed at HEAD.
- **Handshake**: helper + wasm rebuilt from the same tree, `engine_commit`
  identical both sides.

## Browser e2e (CanvasKit, real editor, real wasm engine — screenshots in `browser-e2e/`)

Setup: `dev-setup.sh backend`/`frontend` (ports 8002/3002). A dev-only
window hook (`window.__lumenEditorDebug`, EditorApp.tsx, never installed in
production builds) drives canonical operations through the **exact pipeline
manual edits use** (engine apply → undo frame → history → persistence) —
this is also the harness 1d's browser e2e will reuse.

1. `1b-01-stacked-baseline.png` — clipping column stack + 3 children built
   via `insert_node` ops; solver stacks them (a@90, b@140, c@190).
2. `1b-02-pinned-clipped.png` — `update_node` pins the magenta child
   (`position_mode=absolute`, `absolute_box=(80,150)`, `base_anchor=` the
   solved (30,140)): it lands byte-exact at the box (verified in-engine),
   teal sibling reflows up into the slot.
3. `1b-03-pinned-past-page-edge.png` — second box update (what a 1d drag
   commit emits) pushes it half past the artboard's right edge: **the drag
   is honored and the render clips the overflow at the page boundary — the
   exact Moda behavior from the user's reference screenshot.**
4. `1b-04-relayout-no-snapback.png` — inserting a 4th child forces a full
   stack re-solve (a@90, d@140, c@190) while the pinned node **does not
   move**. Pre-1b, this relayout is what snapped edits back.
5. Undo ×2 (no screenshot): removes the insert (pin undisturbed), then
   restores the *previous* pin box exactly — 1a inverses + 1b solver compose.

## Found while validating (flagged, not 1b regressions)

- **Editor canvas does not render node-level `clip: true`** (page-level clip
  exists — `CanvasKitStage.tsx:169`; image-fit clips exist). The server/Skia
  export path clips correctly (`lumen-skia/src/render.rs:215`). So the
  "watch it get cut off" WYSIWYG for *parent* clips needs a small CanvasKit
  paint change — natural 1d item alongside gestures; until then the page
  boundary case (the one in the user's Moda screenshot) already renders
  faithfully.
- **Pinned-text erosion policy for 1d resize**: LUMV0902/0903/0904 (text
  fit) stay Errors for freehand nodes in 1b — drags never trip them (size
  unchanged), but a 1d *resize-smaller* on pinned text will. Decide at 1d
  whether freehand text-fit overflow downgrades too or the gesture clamps.
- **Sprint-fixtures benchmark deferred to 1d/1e**: the 3 briefs are agent
  *inputs* (prompts), not saved scenes; running them e2e measures the agent
  loop, which 1b doesn't touch (solver output for Managed scenes proven
  byte-identical by the parity/goldens/0b gates). They become the real
  benchmark when gestures (1d) and agent visibility (1e) enter the loop —
  their `freehand_targets` name exactly what to detach/drag.

## Next: 1c — invertible ops

`DetachToFreehand` / `ReattachToLayout` / `ConvertContainerToFree` composite
builders with exact inverses (`operations.rs:945`), baking Hug/Fill→Fixed
from the solved box at detach. The browser run already validated the raw
form of these ops end-to-end; 1c wraps them as named, invertible engine
operations that 1d's UI and Accept/Reject can call.
