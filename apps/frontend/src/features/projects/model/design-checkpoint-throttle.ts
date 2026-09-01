/**
 * The rate limit on the mid-run canvas reload (scene live-streaming rung A).
 *
 * A generating scene commits a P0.4 checkpoint every few seconds, and the
 * platform forwards each one as a `design.checkpoint` frame. Every frame is a
 * genuine new document version, so `designRefreshForEvent` is right to say the
 * canvas should reload on all of them — but *reloading* on all of them would
 * remount the editor faster than a person can read it. This is where that is
 * reconciled: the policy stays "reload", the rate is capped here.
 *
 * Pure, and deliberately free of React: the only thing it touches is
 * `setTimeout`, so it can be driven on a fake clock and reasoned about without
 * a renderer.
 */

/** The floor between two canvas reloads. Founder-set for rung A. */
export const DESIGN_CHECKPOINT_CANVAS_RELOAD_MIN_INTERVAL_MS = 2000;

export interface ThrottledTrailing {
  (): void;
  /** Drop any bump still owed. For teardown — an unmounted surface bumps nothing. */
  cancel(): void;
}

/**
 * Call `fn` at most once per `intervalMs`, **leading and trailing**.
 *
 * The leading edge matters because the first checkpoint of a run should not sit
 * behind a two-second wait for no reason. The trailing edge matters more: the
 * last checkpoint of a burst is the one whose version the canvas will be left
 * showing, so it is the one call that may never be dropped. A plain
 * leading-edge throttle would strand the editor on whichever version happened
 * to fall on a window boundary, with nothing later to correct it.
 *
 * The cooldown chains off the *previous* fire rather than off wall-clock
 * arithmetic, so no reading of `Date.now()` is involved and the guarantee —
 * never two calls closer than `intervalMs` — holds under any arrival pattern.
 */
export function throttleTrailing(
  fn: () => void,
  intervalMs: number,
): ThrottledTrailing {
  let timer: ReturnType<typeof setTimeout> | null = null;
  let pending = false;

  const tick = () => {
    if (!pending) {
      // The burst is over: stop chaining timers and go back to firing on
      // arrival, so the next quiet checkpoint is not made to wait.
      timer = null;
      return;
    }
    pending = false;
    timer = setTimeout(tick, intervalMs);
    fn();
  };

  const throttled = () => {
    if (timer !== null) {
      pending = true;
      return;
    }
    timer = setTimeout(tick, intervalMs);
    fn();
  };

  throttled.cancel = () => {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
    pending = false;
  };

  return throttled;
}
