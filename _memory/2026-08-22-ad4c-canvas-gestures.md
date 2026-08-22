# AD4.C — on-canvas direct manipulation (Lane C close-out), 2026-08-22

Branch `ad4c-canvas-gestures` (worktree `.claude/worktrees/ad4c-lane` off skopje), cut from
`c22f3ef9` (the AD4.R-10 close) at the user's explicit instruction to run Lane C in a parallel
worktree while Lane B ran in colombo. Five commits, all local, frontend-only:
`04d7c008` (pure gesture layer) → `5185a28f` (canvas host: handles, drag, corner resize,
Escape) → `76dd98a3` (review round 1) → `f7790b9b` (final-review fixes) → `4ddb71f3` (docs
record). Regime: Opus scout → brief → Opus implementer → fresh Opus reviewer → scoped
re-review per fix round → controller-driven browser proof → Opus final whole-lane review →
one fix wave → scoped re-review → this note. The scratch ledger
(`.superpowers/sdd/2026-08-20-ad-editor-integration-execution-plan/` in the worktree) dies
with the worktree; this note + git history are the record.

## What shipped (contract §1.9 v1, exactly)

Drag-to-move + corner-resize on the ad canvas, hosted in `scene-artifact-canvas.tsx` over the
extracted `gestureMachine.ts` / `canvaskitGestures.ts` / `selectionChrome.ts`:
- Press pipeline: pan (space/middle) precedence unchanged; corner-handle hit (4 corners ONLY,
  asked directly via `handlePoint` — see F2 below) beats node hit; AD2.5 select semantics
  byte-preserved (empty press clears unconditionally; additive ignored — AD4.E's).
- Preview = render-time descriptor override inside `sceneArtboardModel` + the overlay tracking
  it; the document scene is never touched mid-gesture (AD4.R model held).
- Commit = `dragActionToOperations` / `resizeActionToOperation(allowManagedResize=false)`
  through the session's `applyOps` (AD3.2 editQueue path) as ONE atomic batch = one undo
  frame, intents `"canvas: drag"` / `"canvas: resize"` (typed; runtime-discarded today).
- G-A handles render via the pre-staged `SelectionChrome handles` prop (Variant B, 4×8px
  corners); hidden when `showResizeHandles` is false (locked/managed) or `gestureDisabled`.
- Escape/pointer-cancel = host-level hard reset; `handlePointerUp` ends in unconditional
  `resetGesture()`; Escape listener inert unless an ARMED live gesture exists.
- G-H: `gestureDisabled` prop threaded chat-surface (`chat.threadBusy`) → artifact-stage →
  canvas; artifact route deliberately omits it (same posture + comment as inspectorDisabled).
- Not in v1 (enforced, not just omitted): rotate (the invisible rotate hotspot CANNOT act),
  edge handles, marquee (an empty press can never cross into one), Delete, nudge,
  double-click text, drag-reorder, managed resize.

Gates at close: frontend 1790/1790 (36 new tests; no existing test modified all lane), lint
0 errors, build green, `tsc --noEmit` 84-line baseline byte-identical; root `make check`
clean with EXACTLY the five documented pre-existing pytest reds. Browser-proven on the live
stack (worktree frontend :3020 → shared API :8032 → design :8010; seeded ad at Lane B's own
v172 restore point, returned node-identical): one-version drag persist + ⌘Z restore;
Escape-mid-drag pixel snap-back with a no-op up after cancel; Shift aspect-lock exact
(1.56213) with anchor held and handle-beats-hit-test implicit; locked node = handles vanish +
zero preview movement + zero writes; managed node = outline, no handles, no writes; restore
audit == baseline; zero app console errors. Screenshots /tmp/ad4c-{a,b,c,d}-*.png.

## Rulings (rework any; ledger numbering)

- **C-1** Lane C ran in a parallel worktree, superseding AD4's A1 sequential ruling by user
  instruction; file sets disjoint from Lane B except the keymap-adjacent seam (see merge note).
- **C-2** Plan defect: "reducer up-with-no-commit" doesn't exist (reducer = down/move/up, every
  live up commits). Escape/cancel is a HOST hard reset (upstream's onPointerCancel pattern);
  Escape-while-idle does nothing; upstream has no canvas Escape at all, so ours is a platform
  addition honoring the plan's intent.
- **C-3** Plan defect: bare `controls.applyOperations` would repaint but never persist (no
  editQueue, no D10, no undo frame). Committed gestures ride the session `applyOps` via a new
  `onOperations` prop (upstream's own seam shape); file list expanded to the threading sites.
- **C-4** G-H extends to canvas gestures on the chats route (`gestureDisabled` = threadBusy;
  handles hidden when disabled — a handle that cannot act is a fake affordance; selection
  stays live). Artifact route deliberately ungated (no turn stream; D10 CAS is the net).
- **C-5** Non-editable nodes (locked/managed) get NO drag preview at all — the builders refuse
  silently ([]/null), so a naive host would preview-then-snap-back, the AD4 signature defect
  in gesture form.
- **C-6** Only the 4 corner handles act. `handleAtPoint` (rotate-first, nearest-of-8) was
  demonstrably wrong at the margins — on a 400×6 box the left-edge zone beat both corners; at
  25% zoom the invisible rotate hotspot swallowed a corner press — so the host asks the four
  corners directly (`cornerHandleAtPoint` via the shared `handlePoint`, same 7-screen-px
  tolerance, both regression geometries pinned red-on-old).
- **C-7** Commit-time snap (≤6 canvas px to page/safe-area guides) ships WITHOUT guide chrome:
  guide visuals are not G-A-approved and inventing them is forbidden; suppressing the snap
  would fork the engine's committed math. FOUNDER ITEM: the release can visibly jump ≤6px;
  guide-line visuals should enter the §6-style mockup queue.
- **C-8** The reducer's `additive` select flag is ignored in v1 (multi-select closure is
  AD4.E). Note for AD4.E: the empty-press modifier strip is `down`-only by design — revisit
  that seam when additive semantics land.

## Founder items

1. **C-7 snap-jump** (above) — guides mockup wanted.
2. **A refused drag on a locked/managed node is silent**, and Lane C makes that silence
  user-visible for the first time (upstream shows `disabledReason` chrome we didn't invent).
  `chromeModel.disabledReason` / `canvasDirectEditNotice` exist if a surface is ruled.
3. **No cursor feedback anywhere** (C-7's no-invention discipline): the drawn handle is the
  entire affordance; upstream is equally cursor-less on the interaction layer.
4. **G-H mid-DRAG flip is not gated** (final-review F4): a gesture already in flight when a
  turn starts still commits (starts ARE gated; window is sub-second; D10 is the net), and the
  implementation is half-reactive — handles vanish mid-resize while the in-flight gesture
  still commits. One `useEffect(… resetGesture …)` closes it; land with the G-H follow-up or
  AD4.E if ruled.

## Residuals & traps for whoever continues

- **[AD4.C×engine-port] F9 — pre-existing ported bug, now filed in root CLAUDE.md backlog:**
  BOTH `canvasOperations.ts` drag (:143-152) and resize (:343-347) write page-absolute coords
  into a parent-relative transform for an editable non-pinned non-FREEHAND node under a
  non-origin parent (freehand is the branch that rebases correctly). Invisible on the
  harvested ad (root at origin). Unowned; predates this lane.
- **Resize preview keeps the pre-resize contour/gradient** (final-review 5): the override
  scales box fields but not `contourPath`/gradient paints — upstream parity, but unproven
  either way (the only mid-gesture screenshot is a drag). Watch on a rounded rect.
- **Lane B merge touchpoint** (final-review 6, C-1's prediction): B4's ⌘G/⇧⌘G should land in
  the EXISTING window keydown listener in `scene-artifact-canvas.tsx`, not a third listener.
- **DOM-only fixes**: the unconditional up-reset and the Escape inertness guard (f7790b9b)
  have no runner-level test (React state no adapter seam observes; triggers pinned at the
  pure layer) — proven by construction + the live browser re-proof after the fix. Pointer
  capture and the Escape typing-guard likewise live-proven only. One narrow residual case
  survives (final re-review): an ARMED press whose `setPointerCapture` throws and is then
  released off-stage strands `pressed` until the next press or Escape — Escape now rescues
  it, so the cost is one swallowed Escape keypress in an already-degraded pointer state.
- **G-H live walk is PARTIAL**: thr_ad210_story_portrait still holds its queued turn (Send
  disabled — the busy signal is live) but its artifact would not open into the editor from
  the panel in that state, so the live no-handles/no-drag walk never ran; the gate is
  unit-proven and shape-identical to inspectorDisabled (AD4.R-10 proved that one live).
- **A fresh worktree runs 1738/1754**: the 16 wasm-artifact tests self-skip without the
  gitignored `lumen_wasm` build. Copy `subsystems/clue-design/apps/editor/public/wasm/` from
  a built workspace (the stamp test then proves it matches the commit) or build it.
- Synthetic PointerEvents (bubbles/composed, pointerId 1) drive the host fine for browser
  proofs; CDP `Input.dispatchMouseEvent` is deny-listed in gstack browse. The gesture driver
  recipe lives in this note's git history (`/tmp/ad4c-driver.js` pattern).
- Deferred cosmetics from the reviews (fine where they are): three copies of a
  positive-finite guard (DRY nit); a tautological identity test on `sceneDescriptorPoint`;
  speculative exports (`CORNER_RESIZE_HANDLES`, intent constants) — trim at AD4.E.

## Merge note (for the user)

Lane B (colombo, `integration/frontend-design-part-iv-v6`) and this branch both start at
`c22f3ef9`. File overlap is expected to be zero-to-trivial (B: scene-apply/scene-hydrate/
ad-dummy-inspectors; C: scene-artifact-canvas/scene-canvas-view/scene-gestures + the
onOperations/gestureDisabled threading through artifact-stage, chat-surface, editor-surface,
use-scene-editing-session) — EXCEPT B4's keymap work if it touches the canvas host's
listeners (see merge touchpoint above), and both branches tick plan checkboxes /
annotate the contract, which may collide textually in
`2026-08-20-ad-editor-integration-execution-plan.md` and the contract §6 — trivial merges,
but expect them.
