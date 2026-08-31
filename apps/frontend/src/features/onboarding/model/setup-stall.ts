/**
 * The stall decision for the setting-up poll loop — pure, so it is unit-testable while the hook
 * that uses it is not.
 *
 * Why it exists: `useSetupProgress` bounded only consecutive `none` reads, but after
 * `POST /stage0/setup` the durable `onboarding_input` row makes the read surface serve
 * `starting` — never `none` again — and a healthy fast lane lives its *whole* life in `starting`
 * (it runs inside one enclosing transaction). So a backend driver that dies — a refusal before
 * spend, a process restart, every iteration raising — left the screen spinning forever with no
 * recovery controls. This is the second bound: an in-flight run that reports nothing new for
 * long enough is surfaced as a recoverable terminal, exactly like the `none` budget.
 *
 * It is a *last-resort* bound, not a timer that claims knowledge: the copy at the call site says
 * "taking longer than expected", and the recovery is the same "Try again / Continue anyway" pair
 * the other terminals offer. Anything observable moving — a new field event, a lane transition,
 * an overall status change — resets it, so a slow-but-alive lane is never cut off.
 */

/** What the stall decision reads from a poll tick. Structural: the full `SetupStatus` satisfies it. */
export interface SetupStallSnapshot {
  status: string;
  fast_status?: string | null;
  background_status?: string | null;
  fields?: readonly { field_key: string; lane: string; status: string }[];
  official_site?: {
    run_status?: string;
    phase?: string | null;
    queued?: number;
    leased?: number;
    provider_active?: number;
    reconciliation_pending?: number;
    persistence_pending?: number;
    retry_wait?: number;
    expansion_queued?: number;
    expansion_leased?: number;
    expansion_retry_wait?: number;
    expansion_completed?: number;
    expansion_failed?: number;
    fetched?: number;
    total_pages?: number;
    snapshots?: number;
    extraction_active?: number;
    extraction_materialized?: number;
    extraction_empty?: number;
    extraction_failed?: number;
    last_event_seq?: number | null;
    last_event_kind?: string | null;
  } | null;
}

/**
 * Consecutive unchanged in-flight ticks tolerated before surfacing (40 × 1.5s = 60s — the same
 * budget the `none` path uses, and for the same reason: the fast lane can legitimately hide
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
 * Everything a tick can observably tell us about progress: overall status, both lane statuses,
 * and the per-field event truth. Deliberately NOT the whole payload — `company_website` and
 * friends are constants of the run, and `fact_count` only appears at completion, so including
 * them would neither add nor cost anything, while naming the three progress axes says what the
 * stall bound actually watches.
 */
export function progressSignature(snapshot: SetupStallSnapshot): string {
  const crawl = snapshot.official_site;
  return JSON.stringify([
    snapshot.status,
    snapshot.fast_status ?? null,
    snapshot.background_status ?? null,
    (snapshot.fields ?? []).map((field) => [field.field_key, field.lane, field.status]),
    crawl
      ? [
          crawl.run_status ?? null,
          crawl.phase ?? null,
          crawl.queued ?? null,
          crawl.leased ?? null,
          crawl.provider_active ?? null,
          crawl.reconciliation_pending ?? null,
          crawl.persistence_pending ?? null,
          crawl.retry_wait ?? null,
          crawl.expansion_queued ?? null,
          crawl.expansion_leased ?? null,
          crawl.expansion_retry_wait ?? null,
          crawl.expansion_completed ?? null,
          crawl.expansion_failed ?? null,
          crawl.fetched ?? null,
          crawl.total_pages ?? null,
          crawl.snapshots ?? null,
          crawl.extraction_active ?? null,
          crawl.extraction_materialized ?? null,
          crawl.extraction_empty ?? null,
          crawl.extraction_failed ?? null,
          crawl.last_event_seq ?? null,
          crawl.last_event_kind ?? null,
        ]
      : null,
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
