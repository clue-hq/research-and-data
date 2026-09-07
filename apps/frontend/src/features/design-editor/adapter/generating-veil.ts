/**
 * The website veil's HOLD RULE, as the pure decision it is.
 *
 * The busy signal alone is not enough to drive the blur. Website generation
 * cannot stream: the agent's turn ends on its terminal frame, but the page it
 * wrote only reaches the canvas on the refresh that follows (the canvas-refresh
 * frame bumps `reloadToken`, and the render then walks loading → ready). If the
 * veil lifted on the terminal frame it would uncover the PREVIOUS page for the
 * length of that refetch — the flash the cofounder's handover forbids ("no
 * flash of the old page").
 *
 * So the veil is armed by `generating` and disarmed by the RENDER:
 *
 *  1. `generating` true → the veil is on, and we remember the `reloadToken` the
 *     turn started against (its "start token").
 *  2. `generating` false, having been armed:
 *     - the token never moved → this turn produced no canvas refresh at all (it
 *       failed, it only spoke, it asked a question) → lift immediately. Waiting
 *       for a render that is never coming would strand the blur.
 *     - the token moved → SETTLING: hold the veil until the new token's render
 *       is no longer `loading`. `ready`, `error`, and `empty` all lift it — an
 *       error frame the user cannot see is worse than a lifted veil.
 *  3. never armed → nothing to do.
 *
 * The reducer is total, pure, and idempotent: re-applying it to its own output
 * with the same input returns the SAME object. That is load-bearing, not
 * tidiness — the canvas drives it with React's adjust-state-on-prop-change
 * (a render-time comparison; this repo's react-hooks lint bars set-state in an
 * effect, and an effect would paint one frame of the stale answer anyway), and
 * a reducer that minted a fresh object every pass would never stop re-rendering.
 */

/** The render states `useWebRender` publishes, as the veil cares about them. */
export type VeilRenderKind = "loading" | "ready" | "error" | "empty";

export interface VeilState {
  /** Blur + mark + edge glow are showing. */
  active: boolean;
  /** The `reloadToken` seen when `generating` first became true, held for as
   * long as the turn (and its settle) lasts. Null when the veil is disarmed. */
  startToken: number | null;
  /** The turn is over and a refresh DID arrive: waiting out its render. */
  settling: boolean;
}

export const initialVeilState: VeilState = {
  active: false,
  startToken: null,
  settling: false,
};

/** Keep the previous object when nothing actually moved (see the idempotency
 * note above). */
function stable(prev: VeilState, next: VeilState): VeilState {
  return prev.active === next.active &&
    prev.startToken === next.startToken &&
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
  },
): VeilState {
  if (input.generating) {
    // Rule 1. The start token is captured on the pass generating FIRST becomes
    // true and then held: an armed veil (startToken set, not yet settling) keeps
    // its token even as the agent's own mid-turn refreshes bump `reloadToken`,
    // because the question rule 2 asks is "did anything land since the turn
    // BEGAN". A turn that starts while a previous one is still settling re-arms
    // against the token it actually starts from.
    const armed = prev.startToken !== null && !prev.settling;
    return stable(prev, {
      active: true,
      startToken: armed ? prev.startToken : input.reloadToken,
      settling: false,
    });
  }

  // Rule 3: never armed — the veil has nothing to say about a quiet canvas.
  if (prev.startToken === null) return stable(prev, initialVeilState);

  const refreshed = prev.settling || input.reloadToken !== prev.startToken;
  // Rule 2, first branch: no refresh ever came, so nothing is in flight to wait
  // for. Lift now.
  if (!refreshed) return stable(prev, initialVeilState);

  // Rule 2, second branch: hold through the new token's load, and only that.
  // When the refresh already finished before the turn's terminal frame arrived
  // (token moved AND the render is already ready), this lifts on the very first
  // non-generating pass — the edge case, and no flash either way.
  if (input.renderKind === "loading") {
    return stable(prev, {
      active: true,
      startToken: prev.startToken,
      settling: true,
    });
  }
  return stable(prev, initialVeilState);
}
