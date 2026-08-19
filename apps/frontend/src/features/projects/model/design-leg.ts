/**
 * The design leg, as the chat surface sees it (genweb slice 3, B5).
 *
 * Everything here is pure, and everything here is derived from a **durable**
 * turn-stream frame. The platform emits each `leg.*` frame in the SAME
 * transaction as the leg transition it announces (P3.7 delta 8), so a frame is
 * proof the transition happened — which is why the surface may refresh on one
 * and must never refresh on a timer (founder requirement 1).
 *
 * Three jobs, one module:
 *
 * 1. **the transcript's system lines** — the four lifecycle frames rendered in
 *    the transcript's existing status-line pattern (no new component);
 * 2. **the honest copy** — the wait sentence (no percentage, no ETA: founder
 *    requirements 4 and 5) and a sentence for each typed leg refusal, which
 *    until now landed a bare `failure_code` in front of the user (requirement 7);
 * 3. **the refresh decision** — frame → {gallery feed, open canvas}, so the
 *    component only transports what this decides (requirements 1 and 6).
 */

/** The four durable lifecycle frames (`clue_api.chat.turn_events.TurnEventType`). */
export const DESIGN_LEG_EVENT_TYPES = [
  "leg.opened",
  "leg.awaiting_user",
  "leg.closed",
  "leg.reopened",
] as const;

export type DesignLegEventType = (typeof DESIGN_LEG_EVENT_TYPES)[number];

const LEG_EVENTS: ReadonlySet<string> = new Set(DESIGN_LEG_EVENT_TYPES);

export function isDesignLegEvent(type: string): type is DesignLegEventType {
  return LEG_EVENTS.has(type);
}

/**
 * The honest wait sentence (founder requirement 4, verbatim).
 *
 * Generation is minutes long and its duration is genuinely unknown, so the
 * surface states the range it has actually observed and stops there. A
 * percentage or an ETA would be invented, and requirement 5 forbids both.
 */
export const DESIGN_GENERATION_WAIT_NOTICE =
  "Website generation often takes 5–15 minutes.";

const LEG_CLOSED_NOTICES: Readonly<Record<string, string>> = {
  locked: "Design session closed — the page is locked in.",
  out_of_scope: "Design session closed — back to strategy.",
  abandoned: "Design session closed.",
};

const LEG_CLOSED_FALLBACK = "Design session closed.";

/**
 * The transcript line for one lifecycle frame, or `null` for any other frame.
 *
 * A close reason this build has not been taught falls back to the plain close
 * sentence: the leg *did* close, which is the part the user needs; showing them
 * an unrecognized enum value instead would be a worse answer, not a truer one.
 */
export function designLegNotice({
  type,
  reason,
}: {
  type: string;
  reason: string | null;
}): string | null {
  switch (type) {
    case "leg.opened":
      return "Design session opened — your next message goes to Design.";
    case "leg.reopened":
      return "Design session reopened — your next message goes to Design.";
    case "leg.awaiting_user":
      return "Design is ready for your next message.";
    case "leg.closed":
      return (
        (reason === null ? undefined : LEG_CLOSED_NOTICES[reason]) ??
        LEG_CLOSED_FALLBACK
      );
    default:
      return null;
  }
}

/**
 * The typed leg refusals (`clue_api.design_leg_wiring`), each as a sentence.
 *
 * Every one of these leaves the leg OPEN — the two pre-dispatch refusals never
 * mark it running, and a failed run is put back to `open_awaiting_user` before
 * the turn fails — so the retry is simply the user's next message, and the copy
 * says so rather than offering a control that does not exist.
 *
 * An unrecognized code is returned unchanged. That preserves the surface's
 * existing behaviour for codes this build predates, and a raw code is at least
 * true; inventing a sentence for an unknown failure would not be.
 */
export function designTurnFailureNotice(code: string | null): string | null {
  if (code === null) return null;
  switch (code) {
    case "design_leg_document_finalized":
      return "This page is finalized; revising it needs a new draft revision.";
    case "design_leg_account_unresolved":
      return "This page's target account could not be resolved, so the turn was refused. Nothing was generated.";
    case "design_leg_turn_failed":
      return "Design couldn't finish this page. Nothing was saved — send another message to try again.";
    case "design_leg_turn_crashed":
      return "The design turn stopped unexpectedly. Nothing was saved — send another message to try again.";
    default:
      return code;
  }
}

export interface DesignRefreshDecision {
  /** Re-read the project's design-artifact feed (the rail's gallery cards). */
  refetchFeed: boolean;
  /** Bump the editing session's reload nonce, so an open canvas re-renders. */
  reloadCanvas: boolean;
}

const NO_REFRESH: DesignRefreshDecision = {
  refetchFeed: false,
  reloadCanvas: false,
};

/**
 * What one stream frame should refresh — the whole rule, in one pure function.
 *
 * Only the leg frames qualify, and that is deliberate. They are the only frames
 * that are durable *design* transitions: `leg.awaiting_user` is written in the
 * same transaction that hands the leg back after the design run committed its
 * document version, and `leg.closed` in the transaction that records the exit.
 * A plain `turn.completed` says nothing about a document, so refreshing on it
 * would remount an open canvas after every strategy answer.
 *
 * `leg.opened` / `leg.reopened` refresh the feed but NOT the canvas: the leg's
 * web document is born in that same transaction (slice 2), so a card genuinely
 * appears — and founder ruling F2 (option a) is that it simply appears, with no
 * auto-open and nothing to reload.
 */
export function designRefreshForEvent(
  event: { type: string; threadId: string },
  context: { activeThreadId: string | null },
): DesignRefreshDecision {
  if (
    context.activeThreadId === null ||
    event.threadId !== context.activeThreadId
  ) {
    return NO_REFRESH;
  }
  switch (event.type) {
    case "leg.awaiting_user":
    case "leg.closed":
      return { refetchFeed: true, reloadCanvas: true };
    case "leg.opened":
    case "leg.reopened":
      return { refetchFeed: true, reloadCanvas: false };
    default:
      return NO_REFRESH;
  }
}
