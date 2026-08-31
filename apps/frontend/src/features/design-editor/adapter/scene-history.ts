/**
 * AD3.3: the ad lane's undo/redo depth bookkeeping.
 *
 * The server owns the history stacks; `GET /documents/{id}` reports their true
 * depths and the loader parses them (`engine/scene/documentStore.ts`). That
 * would be the whole story if the ad lane reloaded after every write — but it
 * deliberately does not (AD3.2: the write is optimistic, and a reload is the
 * adoption path for a DISAGREEMENT, not the normal case), so the loaded depths
 * go stale the moment the user edits.
 *
 * This module closes that gap the only honest way: by counting the steps the
 * server ACCEPTED since the load, and adding them to the loaded base. It is
 * bookkeeping, never a guess — every function here records something that has
 * already happened, and every failure path in the controller reloads, which
 * replaces the base and resets the count to zero.
 *
 * Pure, so the rules are testable without a server, a document or a canvas.
 */

/** The depths of the two stacks — what the header menu's rows disable off. */
export interface SceneHistoryDepths {
  undo: number;
  redo: number;
}

/**
 * What has happened since the loaded base.
 *
 * `undo`/`redo` are signed offsets against the base's two depths.
 *
 * `redoCleared` exists because a write is NOT an offset: the design API drops
 * the entire redo stack when a new batch commits, so after one write the base's
 * redo depth stops being part of the answer altogether and only the steps taken
 * since count. Two signed numbers cannot express "the base no longer applies"
 * (any offset large enough to zero one base would be wrong for another, and
 * would then be wrong again for the next undo), so the fact is recorded as the
 * fact it is.
 */
export interface SceneHistoryDelta {
  undo: number;
  redo: number;
  /** A committed write has dropped the server's redo stack since the load. */
  redoCleared: boolean;
}

/** Nothing has happened since the load — the base IS the answer. */
export const NO_HISTORY_DELTA: SceneHistoryDelta = {
  undo: 0,
  redo: 0,
  redoCleared: false,
};

/** An accepted write batch: one more undoable step, and the redo stack is gone. */
export function afterWrite(delta: SceneHistoryDelta): SceneHistoryDelta {
  return { undo: delta.undo + 1, redo: 0, redoCleared: true };
}

/** An applied server undo: one step moves from the undo stack to the redo one. */
export function afterUndo(delta: SceneHistoryDelta): SceneHistoryDelta {
  return {
    undo: delta.undo - 1,
    redo: delta.redo + 1,
    redoCleared: delta.redoCleared,
  };
}

/** An applied server redo: the same step moves back. */
export function afterRedo(delta: SceneHistoryDelta): SceneHistoryDelta {
  return {
    undo: delta.undo + 1,
    redo: delta.redo - 1,
    redoCleared: delta.redoCleared,
  };
}

/**
 * Base (from the document load) + delta, clamped at zero — a depth is never
 * negative.
 *
 * The clamp is only reachable when the count and the server have drifted (a
 * step the server refused, another writer). Zero is the safe direction: it
 * disables the control instead of offering a step that would fail.
 */
export function historyDepths(
  base: SceneHistoryDepths,
  delta: SceneHistoryDelta,
): SceneHistoryDepths {
  return {
    undo: Math.max(0, base.undo + delta.undo),
    redo: Math.max(0, (delta.redoCleared ? 0 : base.redo) + delta.redo),
  };
}
