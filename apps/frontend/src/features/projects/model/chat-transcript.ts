import type { ChatMessage } from "./chat-message";
import type { ChatPart, ChatTextPart } from "./chat-parts";
import type { ChatStreamEvent } from "./chat-events";
import { TERMINAL_TURN_EVENTS } from "./chat-events";
import type { ChatTurn } from "./chat-turn";

/**
 * The one place Clue turn events become ordered message parts.
 *
 * Everything here is pure: `(state, event) -> state`. The repository owns the
 * socket, the controller owns React, and this owns the semantics — which is why
 * the reconnect, duplicate-delivery, replacement, reset and attempt-isolation
 * cases can be tested against synthetic streams with no browser in sight.
 *
 * The five rules, each from charter §§3.2/3.3/3.6:
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
}

export function emptyTranscriptState(): TranscriptState {
  return {
    turns: new Map(),
    order: [],
    seenEventIds: new Set(),
    cursor: 0,
    warnings: [],
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
    default: {
      const next = TURN_STATES[event.type];
      if (next) turn.state = next;
      if (event.failureCode !== null) turn.failureCode = event.failureCode;
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
    const pending = optimistic.find((item) => item.turnId === turnId);

    const durableUser = durable.find((message) => message.role === "user");
    if (durableUser) {
      composed.push(userMessage(durableUser, false));
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
      });
    }

    const durableAssistant = durable.find((message) => message.role === "assistant");
    const parts = livingParts(projected);
    const hasStreamedText = parts.some((part) => part.kind === "text");
    if (durableAssistant || parts.length > 0 || projected) {
      const state = projected?.state ?? (durableAssistant ? "completed" : "queued");
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
        failureCode: projected?.failureCode ?? null,
        optimistic: false,
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
  };
}

function livingParts(turn: TranscriptTurn | undefined): ChatPart[] {
  if (!turn) return [];
  return turn.parts.map((entry) => entry.part);
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
