/**
 * The stall decision for the setting-up poll loop — pure, so it is unit-testable while the hook
 * that uses it is not.
 *
 * Why it exists: `useSetupProgress` bounded only consecutive `none` reads, but the durable run row
 * exists from the moment the screen starts the run, so the read surface serves `starting` and
 * never `none` again — and a healthy fast pass can live a long while in `starting`/`running` with
 * nothing new to report. So a backend driver that dies — a refusal before spend, a process
 * restart, every iteration raising — left the screen spinning forever with no recovery controls.
 * This is the second bound: an in-flight run that reports nothing new for long enough is surfaced
 * as a recoverable terminal, exactly like the `none` budget (which now only covers the window
 * before the first run is posted).
 *
 * It is a *last-resort* bound, not a timer that claims knowledge: the copy at the call site says
 * "taking longer than expected", and the recovery is the same "Try again / Continue anyway" pair
 * the other terminals offer. Anything observable moving — a new step, a step changing status, an
 * overall status change — resets it, so a slow-but-alive run is never cut off.
 */

/** What the stall decision reads from a poll tick. Structural: the full `SetupStatus` satisfies it. */
export interface SetupStallSnapshot {
  status: string;
  steps?: readonly { kind: string; subjectRef?: string | null; status: string }[];
}

/**
 * Consecutive unchanged in-flight ticks tolerated before surfacing (40 × 1.5s = 60s — the same
 * budget the `none` path uses, and for the same reason: the fast steps can legitimately hide
 * progress for a while).
 */
export const MAX_STALL_POLLS = 40;

/**
 * The statuses during which the backend is asserting that work is in flight. Only these can
 * stall: `none` has its own budget, and `complete`/`failed`/`unavailable` are terminal — nothing
 * is expected to move, so an unchanging tick there is correct, not a stall.
 */
const IN_FLIGHT = new Set(["starting", "running"]);

/**
 * Everything a tick can observably tell us about progress: the overall status and the lane's step
 * list — each step's kind, its subject (the per-subject background steps share one kind, so only
 * this tells two personas apart), and its status. Deliberately NOT the whole payload: `run_id` is
 * a constant of the run, and timings/costs move without work moving, so including them would let
 * a dead driver look alive.
 */
export function progressSignature(snapshot: SetupStallSnapshot): string {
  return JSON.stringify([
    snapshot.status,
    (snapshot.steps ?? []).map((step) => [step.kind, step.subjectRef ?? null, step.status]),
  ]);
}

/**
 * The new stall count after observing `next`, given what was last observed and the count so far.
 *
 * - a tick that is not in-flight → `0`: the other channels own those states.
 * - the first observation (`previous === null`) → `0`: learning the state IS progress.
 * - identical observable progress → `count + 1`.
 * - anything moved → `0`.
 */
export function stallAdvance(
  previous: SetupStallSnapshot | null,
  next: SetupStallSnapshot,
  count: number,
): number {
  if (!IN_FLIGHT.has(next.status)) return 0;
  if (previous === null) return 0;
  return progressSignature(previous) === progressSignature(next) ? count + 1 : 0;
}

/** Has an in-flight run gone quiet for the whole budget? */
export function isStalled(count: number): boolean {
  return count >= MAX_STALL_POLLS;
}

/** A surfaced stall is a presentation fallback, not a terminal backend verdict. */
export function shouldStopSetupPolling(
  kind: "failed" | "unavailable" | "session" | "stalled" | null,
): boolean {
  return kind !== null && kind !== "session" && kind !== "stalled";
}
