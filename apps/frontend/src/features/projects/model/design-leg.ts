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
 * One committed design checkpoint, mid-run (scene live-streaming rung A).
 *
 * Not a leg frame: it announces no transition and closes nothing. It says a
 * *version* of the leg's document was committed while the run is still going,
 * which is the whole point — the canvas can now show work in progress instead
 * of a blank wait until `leg.awaiting_user`.
 */
export const DESIGN_CHECKPOINT_EVENT_TYPE = "design.checkpoint";

/**
 * One streamed batch of operations, mid-mutation (scene live-streaming rung B).
 *
 * Weaker than a checkpoint and deliberately so: it announces work that is NOT
 * yet durable, so it refreshes NOTHING here. A canvas may render it
 * optimistically — that decision, and the cursor arithmetic that makes it safe,
 * live in `design-editor/adapter/scene-stream-cursor`. Refreshing the feed or
 * reloading the canvas on one would re-read the durable document several times
 * a second to show it a version it does not yet have.
 */
export const DESIGN_OP_BATCH_EVENT_TYPE = "design.op_batch";

/**
 * The shared wait sentence for ad and website design sessions.
 *
 * Generation is minutes long and its duration is genuinely unknown, so the
 * surface states that clearly without claiming a duration for every format. A
 * percentage or an ETA would be invented, and requirement 5 forbids both.
 */
export const DESIGN_GENERATION_WAIT_NOTICE =
  "Design generation can take several minutes.";

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
      return "Design session opened — generating now.";
    case "leg.reopened":
      return "Design session reopened — generating now.";
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

// Mirrors clue_api.provider_incidents.provider_display / reason_words — the same words the
// research card and the empty overview section use, so one outage reads one way everywhere. A
// provider or reason the tables do not know still renders as itself (true, if terse), like every
// other unknown code here.
const PROVIDER_DISPLAY: Readonly<Record<string, string>> = {
  openrouter: "Model provider",
  exa: "Discovery provider",
  exa_websets: "Discovery provider",
  live_http: "Website fetch",
};
const REASON_WORDS: Readonly<Record<string, string>> = {
  credits_exhausted: "credits exhausted",
  key_limit: "key limit exceeded",
  auth_invalid: "API key rejected",
  account_suspended: "account suspended",
  rate_limited: "rate limited",
  server_error: "server errors",
  timeout: "timeouts",
};

/**
 * `provider_refused:<provider>:<reason>` / `provider_failed:…` as a sentence, or `null` when the
 * code is not one of those. A refusal is a decision no retry changes, so its copy waits for the
 * provider to be restored; a failure is a fault that usually passes, so its copy says try again.
 */
function providerFailureNotice(code: string): string | null {
  const match = /^provider_(refused|failed):([a-z0-9_.-]+):([a-z_]+)$/.exec(code);
  if (!match) return null;
  const [, head, provider, reason] = match;
  const who = PROVIDER_DISPLAY[provider] ?? provider;
  const what = REASON_WORDS[reason] ?? reason.replace(/_/g, " ");
  return head === "refused"
    ? `${who} refused: ${what}. Send another message once it is restored — Clue has been notified.`
    : `${who} failing: ${what}. Send another message to try again — Clue has been notified.`;
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
  const provider = providerFailureNotice(code);
  if (provider !== null) return provider;
  switch (code) {
    case "design_leg_document_finalized":
      return "This page is finalized; revising it needs a new draft revision.";
    case "design_leg_account_unresolved":
      return "This page's target account could not be resolved, so the turn was refused. Nothing was generated.";
    case "design_leg_turn_failed":
    case "design_leg_turn_crashed":
      return "Design stopped before completion. Any saved draft remains available.";
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
 * appears, and there is no open canvas of it yet to reload.
 *
 * Under founder ruling F2 **(b)** (2026-08-19, superseding option (a)) that
 * refreshed feed is also what opens the new document's tab by itself — but the
 * decision is NOT taken here. This frame names only a leg, never a document; the
 * chat surface picks the born artifact out of the refreshed feed
 * (`chat-shell/model/artifact-auto-open`). A `leg.reopened` births no document,
 * so its refresh carries nothing new and opens nothing.
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
    case DESIGN_CHECKPOINT_EVENT_TYPE:
      // The canvas, and only the canvas. A checkpoint is a new *version* of a
      // document that already has its gallery card, so a feed refetch would
      // re-run the rail's read several times a minute for a list that cannot
      // have changed. The reload itself is throttled by the consumer — the
      // rate is transport, this is the policy.
      return { refetchFeed: false, reloadCanvas: true };
    case DESIGN_OP_BATCH_EVENT_TYPE:
      // Nothing. Stated as a case rather than left to fall through `default`,
      // because "an op batch refreshes nothing" is a DECISION (see the
      // constant's docstring), not an unhandled frame.
      return NO_REFRESH;
    default:
      return NO_REFRESH;
  }
}
