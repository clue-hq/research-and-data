/**
 * The website veil's HOLD RULE, as the pure decision it is.
 *
 * The busy signal alone is not enough to drive the blur. Website generation
 * cannot stream: the agent's turn ends on its terminal frame, but the page it
 * wrote only reaches the canvas afterwards — as a reload of the open document
 * (the canvas-refresh frame bumps `reloadToken`) or, on the very first request,
 * as a document being BORN into a stage that had none. Either way the render
 * then walks loading → ready. If the veil lifted on the terminal frame it would
 * uncover the previous page — or the empty state — for the length of that
 * render: the flash the cofounder's handover forbids ("no flash of the old
 * page").
 *
 * So the veil is armed by `generating` and disarmed by the RENDER:
 *
 *  1. `generating` true → the veil is on, and we remember what the pane was
 *     showing when the turn started: its `reloadToken` and its document id.
 *  2. `generating` false, having been armed:
 *     - neither moved → this turn produced no canvas change at all (it failed,
 *       it only spoke, it asked a question) → lift immediately. Waiting for a
 *       render that is never coming would strand the blur until the next turn.
 *     - either moved → SETTLING: hold the veil until that new render is no
 *       longer `loading`. `ready`, `error`, and `empty` all lift it — an error
 *       frame the user cannot see is worse than a lifted veil.
 *  3. never armed → nothing to do.
 *
 * The reducer is total, pure, and idempotent: re-applying it to its own output
 * with the same input returns the SAME object. That is load-bearing, not
 * tidiness — the stage drives it with React's adjust-state-on-prop-change (a
 * render-time comparison; this repo's react-hooks lint bars set-state in an
 * effect, and an effect would paint one frame of the stale answer anyway), and
 * a reducer that minted a fresh object every pass would never stop re-rendering.
 */

/** The render states `useWebRender` publishes, as the veil cares about them.
 * With no document mounted at all the stage reports `empty` — there is no
 * canvas to ask, and an absent page is exactly what `empty` means. */
export type VeilRenderKind = "loading" | "ready" | "error" | "empty";

export interface VeilState {
  /** Blur + mark + edge glow are showing. */
  active: boolean;
  /** The `reloadToken` seen when `generating` first became true, held for as
   * long as the turn (and its settle) lasts. Null when the veil is disarmed. */
  startToken: number | null;
  /** The document the pane was showing when `generating` first became true —
   * null when it was showing none. A turn that BIRTHS the first document
   * changes this, and that birth is a refresh like any other. */
  startDocumentId: string | null;
  /** The turn is over and the canvas DID change: waiting out its render. */
  settling: boolean;
}

export const initialVeilState: VeilState = {
  active: false,
  startToken: null,
  startDocumentId: null,
  settling: false,
};

/** Keep the previous object when nothing actually moved (see the idempotency
 * note above). */
function stable(prev: VeilState, next: VeilState): VeilState {
  return prev.active === next.active &&
    prev.startToken === next.startToken &&
    prev.startDocumentId === next.startDocumentId &&
    prev.settling === next.settling
    ? prev
    : next;
}

export function nextVeilState(
  prev: VeilState,
  input: {
    generating: boolean;
    reloadToken: number;
    renderKind: VeilRenderKind;
    /** The document open in the pane right now, or null for none. */
    documentId: string | null;
  },
): VeilState {
  if (input.generating) {
    // Rule 1. The start pair is captured on the pass generating FIRST becomes
    // true and then held: an armed veil (armed, not yet settling) keeps it even
    // as the agent's own mid-turn refreshes bump `reloadToken`, because the
    // question rule 2 asks is "did anything land since the turn BEGAN". A turn
    // that starts while a previous one is still settling re-arms against the
    // pane it actually starts from.
    const armed = prev.startToken !== null && !prev.settling;
    return stable(prev, {
      active: true,
      startToken: armed ? prev.startToken : input.reloadToken,
      startDocumentId: armed ? prev.startDocumentId : input.documentId,
      settling: false,
    });
  }

  // Rule 3: never armed — the veil has nothing to say about a quiet stage.
  if (prev.startToken === null) return stable(prev, initialVeilState);

  const refreshed =
    prev.settling ||
    input.reloadToken !== prev.startToken ||
    input.documentId !== prev.startDocumentId;
  // Rule 2, first branch: nothing changed on the canvas, so nothing is in
  // flight to wait for. Lift now.
  if (!refreshed) return stable(prev, initialVeilState);

  // Rule 2, second branch: hold through the new render, and only that. When it
  // already finished before the turn's terminal frame arrived (the canvas moved
  // AND is already ready), this lifts on the very first non-generating pass —
  // the edge case, and no flash either way.
  if (input.renderKind === "loading") {
    return stable(prev, {
      active: true,
      startToken: prev.startToken,
      startDocumentId: prev.startDocumentId,
      settling: true,
    });
  }
  return stable(prev, initialVeilState);
}
