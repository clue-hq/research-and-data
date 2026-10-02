/**
 * The mid-run canvas reload decision at a `design.checkpoint` anchor
 * (scene live-streaming rung B, task 9 — fix round 1).
 *
 * Rung A shipped one rule: every checkpoint reloads the open canvas, rate-
 * limited by `design-checkpoint-throttle`. Rung B earns one exception — a
 * checkpoint whose version the canvas is ALREADY showing, because the reload
 * would then swap a picture for an identical one and interrupt a reveal
 * mid-draw to do it.
 *
 * That exception needs TWO facts, and they live in two different places:
 *
 *   1. **the cursor is in sync** — task 8's arithmetic over the frames: the
 *      streamed ledger position equals the position this checkpoint committed;
 *   2. **the pump is clean** — the reveal pump is actually running for this
 *      document, the engine is available, and no apply has been refused.
 *
 * Fact 1 alone is the bug this module was written to close. `inSync` is
 * computed from the FRAMES; it says nothing about what the engine did with
 * them. A pump that latched dirty on a refused batch — or a canvas in the D9
 * read-only state, where no operation can be applied at all — draws nothing,
 * while the cursor goes on reporting in sync at every checkpoint. Suppressing
 * on the cursor alone therefore costs exactly those canvases every mid-run
 * reload until the run hands back: rung A regressing under the failure mode
 * rung B introduced. Live progress is precisely what a five-minute run owes
 * the person watching it, so this composes the two rather than trusting one.
 *
 * Pure, and free of both React and the pump — the surface that owns the pump
 * reports its health as a boolean and nothing about the reveal machinery
 * crosses into the controller.
 */

export interface AnchorReloadInputs {
  /** Task 8's `inSync` for this checkpoint's anchor action. */
  cursorInSync: boolean;
  /**
   * Is the live reveal healthy for the document this checkpoint names?
   *
   * `null` means UNKNOWN — no pump is mounted, the open artifact is a different
   * document, or the surface has not published yet. Unknown is never treated as
   * healthy: the default is rung A's shipped behaviour.
   */
  pumpClean: boolean | null;
}

export interface AnchorReloadDecision {
  /** Bump the (throttled) canvas reload for this checkpoint. */
  reloadCanvas: boolean;
  /**
   * What the pump is told this anchor is.
   *
   * Always the exact opposite of `reloadCanvas`, and that is the point: an
   * anchor that reloads brings a new base document, so the pump must treat it
   * as stale — re-seat from the reloaded document and clear its dirty latch.
   * An anchor that does not reload leaves the pump's working scene standing,
   * which is only safe because it is provably the same scene.
   */
  anchorInSync: boolean;
}

/** `reload = !(cursorInSync && pumpClean)`. One decision, both consumers. */
export function anchorReloadDecision({
  cursorInSync,
  pumpClean,
}: AnchorReloadInputs): AnchorReloadDecision {
  const suppress = cursorInSync && pumpClean === true;
  return { reloadCanvas: !suppress, anchorInSync: suppress };
}
