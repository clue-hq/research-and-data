# Phase AD3 close-out — the ad editor's first write path, 2026-08-21

Branch `integration/frontend-design-part-iv-v4`. Six commits, all local, nothing pushed:

| commit | what |
|---|---|
| `1cc6b5ea` | AD3.1 scene-apply adapter, text rows (fixture-proven) |
| `008f93d4` | AD3.1 review fix — a boxless pin writes its transform |
| `7087c5fe` | AD3.2 CAS write path over the scene editQueue (D10 posture) |
| `3273c452` | AD3.2 review fix — a refused edit must not keep the value it lost |
| `6c548e3a` | AD3.3 server undo/redo wired with the first write |
| `28e02b76` | AD3.3 review fix — a history step drains the write queue first |

Regime: a fresh Opus implementer per sub-slice, my review + fixes before the next
started, and a real-browser proof against the live stack at each gate.

## The one architectural fact that shaped everything

`engine/scene/editQueue.ts` (verbatim upstream) is an **optimistic** pipeline: when a
batch drains it re-fetches the server document and compares it to `localScene()`,
firing `divergence` on any difference. So the ad lane's write order is forced:

1. apply to the live wasm engine (`SceneCanvasControls.applyOperations`, the one new
   canvas seam),
2. repaint + mirror the scene up (the canvas's existing `refresh()` does both),
3. **then** enqueue for persistence.

Persisting first would have reported divergence — and shown the D10 note — on every
accepted keystroke. It also means **no reload on success**: the optimistic apply is
already on screen. The reload nonce is bumped only when the server disagrees, which
is what makes the reload the adoption path for its authoritative scene (D10).

This is the opposite of the web lane (`use-web-manual-edits.ts`), which reloads after
every apply because it has no local engine. Both files say so at the divergence.

## Rulings made (rework any)

1. **AD3.1 — a gradient/multi-layer fill refuses a `textColor` write** rather than
   flattening what the single swatch cannot represent. Mirrors upstream's
   `isGradientGuarded` (`ColorSwatchControl.tsx:228`), which *disables* the control;
   our inspector has no disabled state, so the null contract is the honest equal.
2. **AD3.1 — a pinned node writes its `absolute_box`, not its transform** (the exact
   inverse of `scene-hydrate.ts:350-356`). My first brief said a **boxless** pin should
   refuse; that was my error — hydrate and upstream's `emitPosition` both fall back to
   the transform there, so refusing left a live-looking field doing nothing. Fixed in
   `008f93d4`.
3. **AD3.2 — the ad lane's addressing gate does not use `documentVersion`.** It cannot
   honestly produce one (the extracted loader parsed no `current_version` at the time,
   the scene carries none, and a second fetch would break "one fetch, one engine, one
   scene"), and the queue owns `base_version` itself. The replacement gate is stronger:
   the event's selection IS the session's primary selection AND the live scene really
   carries that node. `addressing.documentVersion` stays `null` on this lane.
4. **AD3.2 — `busy` reports, it does not gate.** Each keystroke is its own batch and
   the local apply has already landed; a single-flight gate would DROP keystrokes.
   History steps are single-flight (they are one deliberate action).
5. **AD3.3 — one marked platform delta to an extracted file.** `documentStore.fetchDocument`
   now parses `current_version` / `undo_stack` / `redo_stack`, mirroring the sibling
   extracted loader `webDocuments.ts:366-369` line for line. Without it the ad lane
   could not say whether an undo step exists, and the only alternatives were a second
   document fetch or a guessed depth. Banner-marked in-file so an upstream re-sync
   re-applies the delta rather than straight-copying.
6. **AD3.3 — a history step drains the write queue first** (`queue.idle()` before the
   POST). An undo landing between a batch's local apply and its POST made the server
   refuse that batch, and D10 then dropped the user's edit under a note it had not
   earned. Ordering, not blocking.
7. Two upstream-prose parses (the queue's rejection sentence, the history step's error)
   are contained in `adapter/scene-reconcile.ts` with tests that pin both upstream
   templates by reading the source files off disk — an upstream reword fails the suite
   instead of silently degrading every rejection to a note.

## The defect the browser found (and how)

A 409 showed the D10 note while the inspector field kept the value the server had just
refused — note, panel and canvas each saying something different. The first fix (key the
inspector on the reload **nonce**) failed live for an instructive reason: the nonce
advances when the reload is *requested*, so the remount re-read the optimistic scene
still on screen. The key now carries `inspectorGeneration`, which the session advances
only when a reloaded document has **arrived** (`onSceneChange` with a reload pending).
A successful write still remounts nothing.

Third session running where only a live interaction exposed the real defect.

## Browser proof (live stack, both mounts)

- **Write + persistence:** font size 54→96 → `POST /operations` 200, server
  `current_version` 1, value survives a full page reload.
- **CAS refusal (D10):** a concurrent writer bumped the version, the next edit got
  409 → the note, a reload, the edit dropped, and the field snapped back to the
  server's value.
- **Divergence:** a successful write whose local scene lacked another writer's change
  fired the same note honestly — the document really had moved on.
- **Undo/redo:** menu Undo 54→66 (v14), Redo → 54 (v15), ⌘Z reverted an 88 edit (v17),
  artifact-route Undo v17→v18. Rows disable off the document's real stacks: Redo was
  disabled until an undo existed.
- **§1.2 sweep:** colour (hex write preserved the existing paint id and detached the
  brand token — the ratified §1.6 trade), weight (400 Regular), horizontal alignment
  (justify — the founder-supplied 4th toggle), lock → `locked: true` **and** a locked
  node refusing every other row, unlock → false.
- Zero console errors beyond the deliberate 409s.

Gate: frontend **1488/1488**, lint clean (3 pre-existing warnings in ported engine
files), build green, root `make check` clean through ruff/format/mypy/import-linter
with exactly the five documented pre-existing pytest reds (zero backend paths in this
diff). The seeded document was restored to its harvested state afterwards (size 54,
weight 700, align left, token fill, unlocked).

## Findings for the founder / later lanes — none blocks AD4

1. **The V-align toggles look live but are inert on a hug-height text box.** The
   contract (§1.2 row 6) says they are dead while the box hugs, `scene-hydrate.ts`
   computes `valignDisabled`, and the write is correctly refused — but **nothing
   consumes that flag**, and the dummy shipped no disabled treatment for a toggle, so
   rendering one would be inventing UI. Founder call (a small mockup gate).
2. **v1 cannot ADD a stroke to a node that has none.** A colour pick resolves the
   existing width (0 for a strokeless node) → clears; a width edit has no colour to
   keep and refuses rather than minting upstream's hardcoded `#256c70`. Contract-literal
   and honest, but it means the ratified Stroke row is unusable on strokeless nodes —
   worth a ruling before AD4's rect/ellipse lanes, where strokes are common.
3. **`documentVersion` is now obtainable** (ruling 5 parses it), so ruling 3's
   compromise could be revisited — but the gate we have is stronger, so nothing is
   pending.
4. **`npx tsc --noEmit` has ~41 pre-existing errors**, all in test files (ported engine
   tests + brand-context), none in production source. The gate is `tsx --test`, which
   strips types without checking. Pre-existing and repo-wide; recorded, not fixed.
5. **One flake seen once:** `iframe/vendor-runtime.test.ts` re-runs the vendor script
   and reads the bundle it writes; a single run read a partial file. Three subsequent
   full runs were clean.
6. Rect / ellipse / group / auto-layout inspectors still show placeholder numbers —
   their controllers are AD4.B, so their write rows cannot be driven through the UI yet
   (the adapter's rows for them are unit-tested and refuse nothing they should not).
