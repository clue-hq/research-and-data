import assert from "node:assert/strict";
import { it } from "node:test";
import {
  NO_HISTORY_DELTA,
  afterRedo,
  afterUndo,
  afterWrite,
  historyDepths,
} from "./scene-history";

/**
 * AD3.3: the depth bookkeeping, proven against the server's own stack
 * behaviour.
 *
 * The rules being asserted are the design API's, not ours: a committed batch
 * pushes one undoable step AND clears the redo stack
 * (`lumen_api/main.py` — undo/redo read `document["undo_stack"]` /
 * `["redo_stack"]`), an undo moves one step from undo to redo, and a redo moves
 * it back.
 */

/** A base that is not zero on either side, so a wrong sign or a swapped field
 * cannot pass by accident. */
const BASE = { undo: 3, redo: 2 };

it("a fresh base with nothing done yet reports the server's own depths", () => {
  assert.deepEqual(historyDepths(BASE, NO_HISTORY_DELTA), { undo: 3, redo: 2 });
});

it("an accepted write adds an undoable step and clears the redo stack", () => {
  const delta = afterWrite(NO_HISTORY_DELTA);
  assert.deepEqual(historyDepths(BASE, delta), { undo: 4, redo: 0 });
});

it("write → undo → redo → write tracks the server step for step", () => {
  // The sequence that matters: the redo stack the first write cleared must not
  // come back when a later undo pushes onto it — the base's 2 redoable batches
  // are gone for good, and only what happened since counts.
  let delta = afterWrite(NO_HISTORY_DELTA);
  assert.deepEqual(historyDepths(BASE, delta), { undo: 4, redo: 0 });
  delta = afterUndo(delta);
  assert.deepEqual(historyDepths(BASE, delta), { undo: 3, redo: 1 });
  delta = afterRedo(delta);
  assert.deepEqual(historyDepths(BASE, delta), { undo: 4, redo: 0 });
  delta = afterWrite(delta);
  assert.deepEqual(historyDepths(BASE, delta), { undo: 5, redo: 0 });
});

it("an undo before any write spends the base's undo stack onto its redo stack", () => {
  const delta = afterUndo(NO_HISTORY_DELTA);
  assert.deepEqual(historyDepths(BASE, delta), { undo: 2, redo: 3 });
});

it("a redo before any write spends the base's redo stack back onto the undo stack", () => {
  const delta = afterRedo(NO_HISTORY_DELTA);
  assert.deepEqual(historyDepths(BASE, delta), { undo: 4, redo: 1 });
});

it("a depth is never negative — the stacks clamp at empty", () => {
  // Only reachable when the bookkeeping and the server disagree (a step the
  // server refused, a concurrent writer). Zero is the honest floor: it disables
  // the control, which is the safe direction.
  const twoUndos = afterUndo(afterUndo(NO_HISTORY_DELTA));
  assert.deepEqual(historyDepths({ undo: 1, redo: 0 }, twoUndos), {
    undo: 0,
    redo: 2,
  });
  const twoRedos = afterRedo(afterRedo(NO_HISTORY_DELTA));
  assert.deepEqual(historyDepths({ undo: 0, redo: 1 }, twoRedos), {
    undo: 2,
    redo: 0,
  });
});

it("a fresh base resets the count — the delta is what happened SINCE a load", () => {
  // What the controller does when `loadGeneration` advances: the reloaded
  // document's own stacks already contain everything that was tracked, so
  // carrying the delta forward would double-count it.
  const delta = afterWrite(afterWrite(NO_HISTORY_DELTA));
  assert.deepEqual(historyDepths({ undo: 5, redo: 0 }, delta), {
    undo: 7,
    redo: 0,
  });
  assert.deepEqual(historyDepths({ undo: 5, redo: 0 }, NO_HISTORY_DELTA), {
    undo: 5,
    redo: 0,
  });
});

it("every step returns a new delta and mutates nothing", () => {
  // The controller holds the delta in React state, so an in-place mutation
  // would not re-render the disabled state it drives.
  const start = NO_HISTORY_DELTA;
  afterWrite(start);
  afterUndo(start);
  afterRedo(start);
  assert.deepEqual(start, NO_HISTORY_DELTA);
  assert.deepEqual(historyDepths(BASE, NO_HISTORY_DELTA), { undo: 3, redo: 2 });
});
