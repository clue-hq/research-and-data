import type { ChatMessage } from "./chat-message";
import type { ChatPart, ChatTextPart } from "./chat-parts";
import type { ChatStreamEvent } from "./chat-events";
import { TERMINAL_TURN_EVENTS } from "./chat-events";
import { designLegNotice } from "./design-leg";
import type { ChatTurn } from "./chat-turn";

/**
 * The one place Clue turn events become ordered message parts.
 *
 * Everything here is pure: `(state, event) -> state`. The repository owns the
 * socket, the controller owns React, and this owns the semantics — which is why
 * the reconnect, duplicate-delivery, replacement, reset and attempt-isolation
 * cases can be tested against synthetic streams with no browser in sight.
 *
 * The six rules — the first five from charter §§3.2/3.3/3.6, the sixth from the
 * dev-lens mini-slice that reuses `text.delta` for a second kind of text:
 *
 * 1. **Dedup by `event_id`** (§3.6, at-least-once delivery). A frame already
 *    applied is a no-op, so a reconnect that replays the backlog byte for byte
 *    produces the same transcript.
 * 2. **Replacement by part id, guarded by revision** (§3.2). `part.updated`
 *    replaces the prior snapshot for the same part; it never appends a
 *    duplicate card, and an out-of-order older revision never overwrites a
 *    newer one.
 * 3. **Text accumulates per attempt, keyed by `delta_index`** (§3.3). Deltas
 *    are stored by index and joined in index order, so a duplicate delta is
 *    idempotent and an out-of-order one still lands in the right place.
 * 4. **Attempt isolation** (§3.3(6)). `part.reset` voids a part; a retry opens
 *    a new attempt with new part ids. Two generations are never spliced.
 * 5. **`stream.reset` means re-fetch, not re-render** (§3.3(5), §3.6). The
 *    turn's projected parts are dropped and `rehydrate` is raised, so the
 *    consumer re-reads the canonical durable message instead of trusting a
 *    projection that could not prove itself.
 * 6. **A delta belongs to the part it names.** `text.delta` is the accumulation
 *    frame, not the assistant-prose frame: the dev-only raw reasoning lens
 *    streams a round's trace on the same frame type, targeting the `reasoning`
 *    part's id. The frame's `part_kind` decides which accumulator runs, so the
 *    trace can never be spliced into the answer — and after a reload it is
 *    simply gone, because unlike prose it has no durable counterpart.
 * 7. **A `leg.*` frame is an announcement, not a part** (genweb slice 3, P3.7
 *    delta 8). It adds one system line to the turn that performed the
 *    transition and moves the thread's design-leg state; it never creates,
 *    replaces or voids a part, and it never changes a turn's own state.
 */

export interface TranscriptPartEntry {
  part: ChatPart;
  /** Which generation attempt produced it — a reset only voids its own. */
  attemptId: string | null;
}

export interface TranscriptTurn {
  turnId: string;
  /** Assistant message id, once any event has named one. */
  messageId: string | null;
  state: TranscriptTurnState;
  failureCode: string | null;
  attemptId: string | null;
  attemptOrdinal: number;
  parts: TranscriptPartEntry[];
  /** `text.delta` payloads by index, per part. Joined in index order. */
  deltas: Map<string, Map<number, string>>;
  /**
   * Design-leg system lines this turn announced, keyed by the frame's own
   * `event_id` (genweb slice 3).
   *
   * Keyed rather than appended so a replayed backlog re-lands the same line
   * instead of a second copy — and so `stream.reset`, which clears the cursor
   * dedup set, cannot duplicate them either. Unlike parts, these have no
   * durable counterpart the consumer could re-read, so a reset does NOT drop
   * them: the transitions they announce definitely happened.
   */
  legNotices: Map<number, string>;
  /** True once this turn has asked its consumer to re-fetch the canonical message. */
  rehydrate: boolean;
}

export type TranscriptTurnState =
  | "unknown"
  | "queued"
  | "running"
  | "awaiting_input"
  | "completed"
  | "failed"
  | "cancelled";

export interface TranscriptState {
  turns: Map<string, TranscriptTurn>;
  /** Submission order — the order turns render in. */
  order: string[];
  seenEventIds: Set<number>;
  /** The highest cursor applied; what a reconnect sends as `Last-Event-ID`. */
  cursor: number;
  /** Non-fatal frames this build could not read, for a visible diagnostic. */
  warnings: string[];
  /**
   * The thread's design leg, as the lifecycle frames have described it so far —
   * or, until one arrives, as the durable thread read seeded it
   * (`seedDesignLeg`).
   *
   * It used to be stream-derived only, and that was honest about the transcript
   * (a leg opened further back than the replayed backlog simply produced no
   * system line) but NOT about the leg: `open: false` was returned both for "the
   * leg is closed" and for "no frame has mentioned one", and the editor lock
   * cannot tell those apart safely. `known` is the difference.
   */
  designLeg: DesignLegState;
}

export interface DesignLegState {
  /**
   * False until either a `leg.*` frame or the durable seed has spoken. A
   * consumer that can act dangerously on the answer must check this first:
   * `open: false, known: false` means "nobody has said", not "there is no leg".
   */
  known: boolean;
  /** True between `leg.opened`/`leg.reopened` and the matching `leg.closed`. */
  open: boolean;
  legId: string | null;
  /**
   * The turn that opened (or reopened) the leg — a head-of-abm turn, not a
   * design turn. Excluded from the "generating" state so the delegating turn's
   * own tail does not claim a website is being generated.
   *
   * `null` on a SEEDED leg: the durable read carries no such turn, and inventing
   * one would put a "generating" badge on a turn that delegated nothing.
   */
  openedByTurnId: string | null;
}

/** Nobody has said anything about a leg yet. */
const UNOBSERVED_LEG: DesignLegState = {
  known: false,
  open: false,
  legId: null,
  openedByTurnId: null,
};

const CLOSED_LEG: DesignLegState = {
  known: true,
  open: false,
  legId: null,
  openedByTurnId: null,
};

/**
 * Seed the leg from the DURABLE thread read (`ChatThread.designLeg`).
 *
 * The frame backlog replays only the last few turns, so a leg opened before it
 * is invisible to the stream — and "invisible" read as "closed" is what
 * unlocked the scene editor mid-run (task 4 fix round 1, finding I1). The
 * thread wire's speaker projection is the platform's own answer, and this is
 * where it lands.
 *
 * It is a FLOOR, never an override: it applies only while nothing has been
 * observed, so a leg the stream watched close stays closed and a frame that
 * arrives after a seed replaces it. Returns the same state when it changes
 * nothing, so a repeated load costs no render.
 */
export function seedDesignLeg(
  state: TranscriptState,
  seed: { legId: string | null; open: boolean },
): TranscriptState {
  if (state.designLeg.known) return state;
  return {
    ...state,
    designLeg: {
      known: true,
      open: seed.open,
      legId: seed.legId,
      openedByTurnId: null,
    },
  };
}

export function emptyTranscriptState(): TranscriptState {
  return {
    turns: new Map(),
    order: [],
    seenEventIds: new Set(),
    cursor: 0,
    warnings: [],
    designLeg: UNOBSERVED_LEG,
  };
}

function blankTurn(turnId: string): TranscriptTurn {
  return {
    turnId,
    messageId: null,
    state: "unknown",
    failureCode: null,
    attemptId: null,
    attemptOrdinal: 0,
    parts: [],
    deltas: new Map(),
    legNotices: new Map(),
    rehydrate: false,
  };
}

function turnOf(state: TranscriptState, turnId: string): TranscriptTurn {
  const existing = state.turns.get(turnId);
  if (existing) return existing;
  const created = blankTurn(turnId);
  state.turns.set(turnId, created);
  state.order.push(turnId);
  return created;
}

const TURN_STATES: Partial<Record<string, TranscriptTurnState>> = {
  "turn.accepted": "queued",
  "turn.started": "running",
  "turn.retrying": "running",
  "turn.awaiting_input": "awaiting_input",
  "turn.completed": "completed",
  "turn.failed": "failed",
  "turn.cancelled": "cancelled",
};

function transcriptStateOf(value: string): TranscriptTurnState {
  switch (value) {
    case "queued":
    case "running":
    case "awaiting_input":
    case "completed":
    case "failed":
    case "cancelled":
      return value;
    default:
      return "unknown";
  }
}

/**
 * Apply one event. Returns a **new** state object (the map/array contents are
 * rebuilt only where they changed, so React sees a fresh reference per apply).
 */
export function applyChatStreamEvent(
  previous: TranscriptState,
  event: ChatStreamEvent,
): TranscriptState {
  // Rule 1: at-least-once delivery is deduplicated by cursor.
  if (event.eventId !== null && previous.seenEventIds.has(event.eventId)) {
    return previous;
  }

  const state: TranscriptState = {
    turns: new Map(previous.turns),
    order: [...previous.order],
    seenEventIds: new Set(previous.seenEventIds),
    cursor: previous.cursor,
    warnings: previous.warnings,
    designLeg: previous.designLeg,
  };
  if (event.eventId !== null) {
    state.seenEventIds.add(event.eventId);
    state.cursor = Math.max(state.cursor, event.eventId);
  }

  if (event.type === "stream.hello") return state;

  const source = turnOf(state, event.turnId);
  const turn: TranscriptTurn = {
    ...source,
    parts: [...source.parts],
    deltas: new Map(source.deltas),
    legNotices: new Map(source.legNotices),
  };
  state.turns.set(event.turnId, turn);
  if (event.messageId !== null) turn.messageId = event.messageId;
  if (event.generationAttemptId !== null && event.type !== "part.reset") {
    if (turn.attemptId !== event.generationAttemptId) {
      turn.attemptId = event.generationAttemptId;
      turn.attemptOrdinal += 1;
    }
  }

  switch (event.type) {
    case "stream.reset": {
      // Rule 5. Everything projected for this turn is disowned; the durable
      // message is the authority and the consumer is told to go and read it.
      turn.parts = [];
      turn.deltas = new Map();
      turn.rehydrate = true;
      // A reset also invalidates the cursor's meaning: the connect-time reset
      // restarts the backlog from zero, and dedup must not swallow it.
      state.seenEventIds = new Set();
      state.cursor = 0;
      return state;
    }
    case "part.created":
    case "part.updated":
    case "part.completed":
    case "part.failed": {
      if (event.part === null) {
        return withWarning(state, `${event.type} carried no part snapshot`);
      }
      upsertPart(turn, event.part, event.generationAttemptId);
      return state;
    }
    case "part.reset": {
      if (event.partId === null) return state;
      // Rule 4: only this part, only its own attempt's projection.
      turn.parts = turn.parts.filter((entry) => entry.part.partId !== event.partId);
      turn.deltas.delete(event.partId);
      return state;
    }
    case "text.start": {
      if (event.partId === null) return state;
      turn.deltas.set(event.partId, new Map());
      upsertPart(
        turn,
        {
          kind: "text",
          partId: event.partId,
          revision: 1,
          text: "",
          streaming: true,
          failed: false,
          failureReason: null,
        },
        event.generationAttemptId,
      );
      return state;
    }
    case "text.delta": {
      if (event.partId === null || event.delta === null) return state;
      // Rule 3: index-keyed, so duplicates are idempotent and gaps are visible.
      const deltas = new Map(turn.deltas.get(event.partId) ?? new Map<number, string>());
      deltas.set(event.deltaIndex ?? deltas.size, event.delta);
      turn.deltas.set(event.partId, deltas);
      // Rule 6: a delta belongs to whichever part it names, not necessarily to a
      // text part. The dev-only raw reasoning lens streams a round's trace as
      // `text.delta` frames carrying the *reasoning* part's id — the same frame
      // type, because indexed accumulation is exactly what it needs and a second
      // vocabulary would have bought nothing. Routing by the frame's own
      // `part_kind` is what keeps the two apart: without it, the accumulator
      // below would replace the round's status card with a text part and the
      // trace would be spliced into the assistant's answer.
      if (isReasoningDelta(turn, event)) {
        upsertReasoningText(turn, event.partId, joinDeltas(deltas));
        return state;
      }
      upsertText(turn, event.partId, event.generationAttemptId, {
        text: joinDeltas(deltas),
        streaming: true,
      });
      return state;
    }
    case "text.end": {
      if (event.partId === null) return state;
      upsertText(turn, event.partId, event.generationAttemptId, {
        streaming: false,
      });
      return state;
    }
    case "leg.opened":
    case "leg.reopened":
    case "leg.awaiting_user":
    case "leg.closed": {
      // Rule 7 (genweb slice 3): a leg frame is the durable announcement of a
      // leg transition. It becomes one transcript system line on the turn that
      // performed it, and it moves the thread's leg state — nothing else. It
      // never touches parts, prose, or the turn's own lifecycle state.
      const notice = designLegNotice({ type: event.type, reason: event.reason });
      if (notice !== null && event.eventId !== null) {
        turn.legNotices.set(event.eventId, notice);
      }
      state.designLeg =
        event.type === "leg.closed"
          ? CLOSED_LEG
          : event.type === "leg.awaiting_user"
            ? {
                // The leg is still open; only the frames that OPEN it name the
                // delegating turn, so an awaiting frame must not overwrite it.
                known: true,
                open: true,
                legId: event.legId ?? state.designLeg.legId,
                openedByTurnId: state.designLeg.openedByTurnId,
              }
            : {
                known: true,
                open: true,
                legId: event.legId,
                openedByTurnId: event.turnId,
              };
      return state;
    }
    default: {
      const next = TURN_STATES[event.type];
      if (next) turn.state = next;
      if (event.failureCode !== null) turn.failureCode = event.failureCode;
      if (event.type === "turn.cancelled") turn.failureCode = null;
      if (event.type === "turn.cancelled" || event.type === "turn.failed") {
        markStreamingTextFailed(turn, event.reason ?? event.failureCode);
      }
      if (TERMINAL_TURN_EVENTS.has(event.type) && event.replayed) {
        // A replayed turn streamed nothing this time round; its text lives only
        // in the durable message.
        turn.rehydrate = true;
      }
      return state;
    }
  }
}

function withWarning(state: TranscriptState, warning: string): TranscriptState {
  return state.warnings.includes(warning)
    ? state
    : { ...state, warnings: [...state.warnings, warning] };
}

function joinDeltas(deltas: ReadonlyMap<number, string>): string {
  return [...deltas.entries()]
    .sort((left, right) => left[0] - right[0])
    .map(([, value]) => value)
    .join("");
}

function upsertPart(
  turn: TranscriptTurn,
  part: ChatPart,
  attemptId: string | null,
): void {
  const index = turn.parts.findIndex((entry) => entry.part.partId === part.partId);
  if (index === -1) {
    turn.parts.push({ part, attemptId });
    return;
  }
  // Rule 2: replacement in place, and never backwards.
  if (turn.parts[index].part.revision > part.revision) return;
  turn.parts[index] = { part, attemptId };
}

function upsertText(
  turn: TranscriptTurn,
  partId: string,
  attemptId: string | null,
  patch: Partial<Pick<ChatTextPart, "text" | "streaming">>,
): void {
  const index = turn.parts.findIndex((entry) => entry.part.partId === partId);
  const current: ChatTextPart =
    index === -1 || turn.parts[index].part.kind !== "text"
      ? {
          kind: "text",
          partId,
          revision: 1,
          text: "",
          streaming: true,
          failed: false,
          failureReason: null,
        }
      : (turn.parts[index].part as ChatTextPart);
  const next: ChatTextPart = { ...current, ...patch, revision: current.revision + 1 };
  if (index === -1) turn.parts.push({ part: next, attemptId });
  else turn.parts[index] = { part: next, attemptId };
}

/**
 * Whether this `text.delta` carries a reasoning trace rather than assistant prose.
 *
 * The frame's own `partKind` is the authority — it is what the backend stamps —
 * and the part already in the turn is the fallback, for a consumer that attached
 * mid-round and has the card but not the frame that opened it.
 */
function isReasoningDelta(
  turn: TranscriptTurn,
  event: ChatStreamEvent,
): boolean {
  if (event.partKind === "reasoning") return true;
  const existing = turn.parts.find((entry) => entry.part.partId === event.partId);
  return existing?.part.kind === "reasoning";
}

/**
 * Fold a reasoning trace into the round's existing card.
 *
 * Two deliberate differences from `upsertText`. It **never creates** a part: a
 * trace with no round to belong to is a frame out of order, and inventing a
 * reasoning card for it would show a round that never started. And it **does not
 * bump `revision`** — the round's own `part.completed` snapshot arrives with the
 * next revision and carries the whole accumulated trace, so incrementing here
 * would make the local copy outrank the server's closing state and rule 2 would
 * silently drop it.
 */
function upsertReasoningText(
  turn: TranscriptTurn,
  partId: string,
  text: string,
): void {
  const index = turn.parts.findIndex((entry) => entry.part.partId === partId);
  if (index === -1) return;
  const current = turn.parts[index];
  if (current.part.kind !== "reasoning") return;
  turn.parts[index] = {
    ...current,
    part: { ...current.part, text, textEphemeral: true },
  };
}

function markStreamingTextFailed(turn: TranscriptTurn, reason: string | null): void {
  turn.parts = turn.parts.map((entry) =>
    entry.part.kind === "text" && entry.part.streaming
      ? {
          ...entry,
          part: {
            ...entry.part,
            streaming: false,
            failed: true,
            failureReason: reason,
          },
        }
      : entry,
  );
}

// --- the rendered transcript --------------------------------------------

export interface TranscriptMessage {
  id: string;
  turnId: string;
  role: "user" | "assistant";
  createdAt: string | null;
  /** The durable body when one exists; otherwise `null`. */
  body: string | null;
  bodyUnavailableReason: string | null;
  parts: readonly ChatPart[];
  refs: ChatMessage["refs"];
  /** True while this message's turn is still producing. */
  live: boolean;
  state: TranscriptTurnState;
  failureCode: string | null;
  /** True for a locally-submitted turn the server has not yet echoed back. */
  optimistic: boolean;
  /**
   * Design-leg system lines this turn announced, in frame order (slice 3).
   *
   * Ordered by `event_id`, which is the stream's own global sequence, so the
   * open/hand-back/close lines read in the order they actually happened.
   */
  legNotices: readonly string[];
  /**
   * True while this turn is running INSIDE an open design leg — i.e. the
   * message the user sent went to Design and a website is being generated.
   *
   * Derived from the leg frames alone (the turn read carries no role), and the
   * delegating turn that opened the leg is excluded: it is a strategy turn that
   * generates nothing. When the backlog does not reach the opening frame this
   * is simply `false` — the surface says less, never something untrue.
   */
  generatingDesign: boolean;
}

export interface OptimisticTurn {
  turnId: string;
  text: string;
  requestedAt: string;
}

/**
 * Compose the durable transcript, the live projections, and anything the user
 * has just submitted into one ordered list.
 *
 * The composition rule for assistant prose is the important one: a turn's text
 * renders from its **streamed text parts while they exist**, and from the
 * durable body otherwise. §3.3(5) guarantees the two are byte-identical on a
 * successful attempt, so neither doubles the other; and after a `stream.reset`
 * the parts are gone, which is exactly when the durable body must take over.
 */
export function composeTranscript({
  messages,
  turns,
  stream,
  optimistic = [],
}: {
  messages: readonly ChatMessage[];
  turns: readonly ChatTurn[];
  stream: TranscriptState;
  optimistic?: readonly OptimisticTurn[];
}): TranscriptMessage[] {
  const byTurn = new Map<string, ChatMessage[]>();
  for (const message of messages) {
    const bucket = byTurn.get(message.turnId);
    if (bucket) bucket.push(message);
    else byTurn.set(message.turnId, [message]);
  }

  const turnOrder: string[] = [];
  const seen = new Set<string>();
  const push = (turnId: string) => {
    if (seen.has(turnId)) return;
    seen.add(turnId);
    turnOrder.push(turnId);
  };
  // Submission order is the backend's; durable message sequence orders the rest.
  for (const turn of turns) push(turn.turnId);
  for (const message of [...messages].sort((a, b) => a.sequence - b.sequence)) {
    push(message.turnId);
  }
  for (const pending of optimistic) push(pending.turnId);
  for (const turnId of stream.order) push(turnId);

  const composed: TranscriptMessage[] = [];
  for (const turnId of turnOrder) {
    const durable = (byTurn.get(turnId) ?? [])
      .slice()
      .sort((a, b) => a.sequence - b.sequence);
    const projected = stream.turns.get(turnId);
    const durableTurn = turns.find((turn) => turn.turnId === turnId);
    const pending = optimistic.find((item) => item.turnId === turnId);

    const derived = durableTurn?.derivation != null;
    const answeredGate = durableTurn?.answeredGateId != null;
    const durableUser = durable.find((message) => message.role === "user");
    const acceptedUser = durableTurn?.submissionMessage;
    if (derived) {
      // A derived turn (a design-leg redelivery or first turn) carries the user's own bytes,
      // which the transcript already shows under the turn they were typed on.
    } else if (answeredGate) {
      // R-11.4: a card answer shows only on its card. The durable user row stays for the
      // agent's history; the transcript renders no bubble for it.
    } else if (durableUser) {
      composed.push(userMessage(durableUser, false));
    } else if (acceptedUser) {
      composed.push(userMessage(acceptedUser, false));
    } else if (pending) {
      composed.push({
        id: `optimistic:${turnId}`,
        turnId,
        role: "user",
        createdAt: pending.requestedAt,
        body: pending.text,
        bodyUnavailableReason: null,
        parts: [],
        refs: [],
        live: false,
        state: projected?.state ?? "queued",
        failureCode: null,
        optimistic: true,
        legNotices: [],
        generatingDesign: false,
      });
    }

    const durableAssistant = durable.find((message) => message.role === "assistant");
    const parts = livingParts(projected);
    const hasStreamedText = parts.some((part) => part.kind === "text");
    if (durableAssistant || parts.length > 0 || projected || durableTurn) {
      // The turns read is the cold-reload authority. A stream projection may
      // lead it during a live transition, but the absence of replay frames must
      // never erase a durable cancelled/failed/queued assistant receipt.
      const durableState = durableTurn ? transcriptStateOf(durableTurn.state) : undefined;
      // Older Stop attempts emitted a generic failure before their cancellation,
      // and SSE closed at that first terminal. The persisted cancellation is the
      // later truth even when replay can only reconstruct the earlier failure.
      // A stale running read must still yield to a live terminal stream frame.
      const state = durableState === "cancelled"
        ? durableState
        : projected?.state ?? durableState ?? (durableAssistant ? "completed" : "queued");
      composed.push({
        id: durableAssistant?.id ?? projected?.messageId ?? `pending:${turnId}`,
        turnId,
        role: "assistant",
        createdAt: durableAssistant?.createdAt ?? null,
        body: hasStreamedText ? null : (durableAssistant?.body ?? null),
        bodyUnavailableReason: durableAssistant?.bodyUnavailableReason ?? null,
        parts,
        refs: durableAssistant?.refs ?? [],
        live: state === "queued" || state === "running",
        state,
        failureCode: state === "cancelled" ? null : projected?.failureCode ?? null,
        optimistic: false,
        legNotices: orderedLegNotices(projected),
        generatingDesign:
          state === "running" &&
          stream.designLeg.open &&
          stream.designLeg.openedByTurnId !== turnId,
      });
    }
  }
  return composed;
}

function userMessage(message: ChatMessage, optimistic: boolean): TranscriptMessage {
  return {
    id: message.id,
    turnId: message.turnId,
    role: "user",
    createdAt: message.createdAt,
    body: message.body,
    bodyUnavailableReason: message.bodyUnavailableReason,
    parts: [],
    refs: message.refs,
    live: false,
    state: "completed",
    failureCode: null,
    optimistic,
    legNotices: [],
    generatingDesign: false,
  };
}

/** The turn's leg lines in stream order (`event_id` is globally monotone). */
function orderedLegNotices(turn: TranscriptTurn | undefined): readonly string[] {
  if (!turn || turn.legNotices.size === 0) return [];
  return [...turn.legNotices.entries()]
    .sort((left, right) => left[0] - right[0])
    .map(([, notice]) => notice);
}

function livingParts(turn: TranscriptTurn | undefined): ChatPart[] {
  if (!turn) return [];
  const terminal = ["awaiting_input", "completed", "failed", "cancelled"].includes(
    turn.state,
  );
  if (!terminal) return turn.parts.map((entry) => entry.part);
  return turn.parts.map(({ part }) => {
    if (part.kind === "reasoning" && part.state === "active") {
      return {
        ...part,
        state:
          turn.state === "cancelled" || turn.state === "failed"
            ? ("error" as const)
            : ("complete" as const),
      };
    }
    if (part.kind === "agent_activity") {
      return {
        ...part,
        steps: part.steps.map((step) =>
          step.status !== "active"
            ? step
            : {
                ...step,
                status:
                  turn.state === "cancelled" || turn.state === "failed"
                    ? ("error" as const)
                    : ("complete" as const),
              },
        ),
      };
    }
    return part;
  });
}

/**
 * Fold one durable message page into what is already loaded (Slice C C5).
 *
 * The messages read serves the *newest* page first and pages backward on a
 * before-cursor, so the controller holds a growing window that can receive a
 * page at either end: an older page prepends during scrollback, and a reload's
 * fresh newest page lands after older history is already loaded. One rule
 * covers both: union by message id (the incoming durable row wins), ordered by
 * the thread's own gap-free `sequence`. Deduplication against optimistic and
 * streamed stand-ins is not re-implemented here — `composeTranscript`'s
 * identity guards (turn id, durable-wins) are the merge seam, and they receive
 * the merged list.
 *
 * Reference-preserving: a message already loaded and absent from the incoming
 * page survives by identity, so React re-renders only what actually changed.
 */
export function mergeThreadMessages(
  loaded: readonly ChatMessage[],
  page: readonly ChatMessage[],
): ChatMessage[] {
  if (page.length === 0) return [...loaded];
  const incoming = new Map(page.map((message) => [message.id, message]));
  const merged = loaded.map((message) => incoming.get(message.id) ?? message);
  const known = new Set(loaded.map((message) => message.id));
  for (const message of page) {
    if (!known.has(message.id)) merged.push(message);
  }
  return merged.sort((left, right) => left.sequence - right.sequence);
}

/** Every gate id the transcript currently shows a card for. */
export function gateIdsInTranscript(
  transcript: readonly TranscriptMessage[],
): string[] {
  const ids = new Set<string>();
  for (const message of transcript) {
    for (const part of message.parts) {
      if (part.kind === "gate" && part.gateRef.objectId) {
        ids.add(part.gateRef.objectId);
      }
    }
    for (const ref of message.refs) {
      if (ref.flavor === "open_gate") ids.add(ref.objectId);
    }
  }
  return [...ids];
}

/** The turns whose projections asked to be rehydrated from the durable read. */
export function turnsAwaitingRehydration(state: TranscriptState): string[] {
  return [...state.turns.values()]
    .filter((turn) => turn.rehydrate)
    .map((turn) => turn.turnId);
}
