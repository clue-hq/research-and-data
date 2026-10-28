import { z } from "zod";
import { ChatPartSnapshotSchema, type ChatPart } from "./chat-parts";

/**
 * The §3.2 turn-event envelope, as `TurnEventRow.envelope()` puts it on the wire.
 *
 * Two identifiers, two jobs (charter §3.2, mirrored in `chat/turn_events.py`):
 *
 * - `eventId` is globally monotone. It is the SSE `id:` field, the
 *   `Last-Event-ID` cursor, and the deduplication key for at-least-once
 *   delivery.
 * - `sequence` is monotone *within one turn*, so a consumer can gap-check one
 *   conversation without observing the rest of the workspace.
 *
 * Two frames are generated at connect rather than stored, and therefore carry
 * neither identifier: `stream.hello` and the connect-time `stream.reset` the
 * replay planner emits when a cursor falls outside the horizon. They are
 * accepted with both fields absent instead of being forced into the durable
 * shape — pretending a synthetic frame has a cursor would let a consumer
 * advance past events it never saw.
 */

export const CHAT_STREAM_SCHEMA_VERSION = "1";

/** The closed §3.2 vocabulary. `stream.hello` is connect-only and never stored. */
export const ChatStreamEventTypeSchema = z.enum([
  "turn.accepted",
  "turn.started",
  "turn.awaiting_input",
  "turn.completed",
  "turn.failed",
  "turn.cancelled",
  "turn.retrying",
  "part.created",
  "part.updated",
  "part.completed",
  "part.failed",
  "part.reset",
  "text.start",
  "text.delta",
  "text.end",
  // P3.7 delta 8: the design-leg lifecycle rides this same turn stream. Each
  // frame is emitted in the transaction that performs the durable transition it
  // announces, carries `leg_id`, and `leg.closed` also carries the exit
  // `reason`. Genweb slice 3 renders them as transcript system lines.
  "leg.opened",
  "leg.awaiting_user",
  "leg.closed",
  "leg.reopened",
  // Scene live-streaming rung A: one committed P0.4 design checkpoint,
  // forwarded mid-run off the design run's own outbox
  // (`clue_api.design_fleet`). Unlike the `leg.*` frames it is not a lifecycle
  // transition and writes nothing to the transcript — it exists so an open
  // canvas can catch up with a version the document already has.
  "design.checkpoint",
  // Scene live-streaming rung B: the operations of a single mutation, streamed
  // as the design agent makes them, with the position that batch ends at in the
  // run's operation ledger. Unlike a checkpoint it announces work that is NOT
  // yet durable — the canvas may render it optimistically and reconciles
  // against the checkpoint behind it, which is why both frames report positions
  // in the same ledger.
  "design.op_batch",
  "stream.hello",
  "stream.reset",
]);

export type ChatStreamEventType = z.infer<typeof ChatStreamEventTypeSchema>;

/** The event types that end a turn — "is this still live?" is derived, never stored. */
export const TERMINAL_TURN_EVENTS: ReadonlySet<ChatStreamEventType> = new Set([
  "turn.completed",
  "turn.failed",
  "turn.cancelled",
  "turn.awaiting_input",
]);

/**
 * The envelope, before the payload is narrowed by type.
 *
 * The backend spreads each event's payload members into the top level of the
 * `data:` object, so this schema is deliberately open: unknown members are
 * preserved for the per-type readers below rather than rejected.
 */
const EnvelopeSchema = z.looseObject({
  schema_version: z.string(),
  event_id: z.number().int().optional(),
  sequence: z.number().int().optional(),
  occurred_at: z.string().optional(),
  project_id: z.string().min(1),
  thread_id: z.string().min(1),
  turn_id: z.string().min(1),
  generation_attempt_id: z.string().optional(),
  message_id: z.string().optional(),
  part_id: z.string().optional(),
  part_kind: z.string().optional(),
  run_id: z.string().optional(),
  delta_index: z.number().int().optional(),
  /** Present on every `leg.*` frame — the design leg the transition belongs to. */
  leg_id: z.string().optional(),
  type: ChatStreamEventTypeSchema,
});

/**
 * The mark one `design.checkpoint` frame announces.
 *
 * Every member is nullable **on purpose**. The platform forwarder copies across
 * only the keys the design event actually carried
 * (`clue_api.design_fleet._forwarded_frame`), so a partial payload is an
 * ordinary frame rather than a broken one — and the only thing the surface
 * decides from a checkpoint is "reload the canvas", which needs none of them.
 * Refusing the frame over an unreadable field would trade the whole live
 * reload for a value nothing renders.
 */
export interface DesignCheckpoint {
  /** The design document the committed version belongs to. */
  documentId: string | null;
  /** The document version this checkpoint committed. Monotone per document. */
  version: number | null;
  /** How many operations the checkpoint carried. A counter, not a list. */
  operations: number | null;
  /** Whether the engine's preflight was clean when it committed. */
  preflightClean: boolean | null;
}

/**
 * One `design.op_batch` payload — a mutation's operations, mid-run.
 *
 * Read leniently for the same reason {@link DesignCheckpoint} is: the forwarder
 * copies across only the keys the design event carried, and it deliberately
 * drops `operations` (keeping `operations_total`) once a batch exceeds its size
 * ceiling. A POSITION-ONLY frame is therefore an ordinary frame, not a broken
 * one, and refusing it would cost the consumer the position it needs to know it
 * has fallen behind.
 *
 * `operations` is validated as a whole or read as absent — never filtered. Half
 * a batch applied to a canvas is a corrupted document, which is exactly why the
 * platform sends a bare position rather than a truncated list; a member this
 * build cannot read costs the batch, and the cursor waits for the next
 * checkpoint. The members stay untyped records here: the `Operation` contract
 * belongs to the design editor, and this is the chat stream's boundary.
 */
export interface DesignOpBatch {
  /** The design document these operations edit (the leg's pinned document). */
  documentId: string | null;
  /** The batch, or `null` when it was absent, oversize, or unreadable. */
  operations: readonly Record<string, unknown>[] | null;
  /** Where this batch ENDS in the run's operation ledger. A position. */
  operationsTotal: number | null;
  /** The authoring iteration that produced it. */
  iteration: number | null;
}

const CommonIdentitySchema = z.object({
  project_id: z.string().min(1),
  thread_id: z.string().min(1),
  turn_id: z.string().min(1),
});

export interface ChatStreamEvent {
  schemaVersion: string;
  /** Absent on the two connect-generated frames; never invented. */
  eventId: number | null;
  sequence: number | null;
  occurredAt: string | null;
  projectId: string;
  threadId: string;
  turnId: string;
  generationAttemptId: string | null;
  messageId: string | null;
  partId: string | null;
  partKind: string | null;
  runId: string | null;
  deltaIndex: number | null;
  /** Present on the four `leg.*` lifecycle frames; null everywhere else. */
  legId: string | null;
  /** On `leg.opened`/`leg.reopened`: true when the server opened the leg on its own design turn
   * (a comment moved it to the page it was left on), so this turn designs rather than delegates. */
  legTurn: boolean;
  /** Present on `design.checkpoint`; null on every other frame. */
  checkpoint: DesignCheckpoint | null;
  /** Present on `design.op_batch`; null on every other frame. */
  opBatch: DesignOpBatch | null;
  type: ChatStreamEventType;
  /** Present on `part.created|updated|completed|failed`. */
  part: ChatPart | null;
  /** Present on `text.delta`. Append-only, ordered by `deltaIndex`. */
  delta: string | null;
  /** `stream.reset` / `part.reset` / `turn.*` carry a stable reason or status code. */
  reason: string | null;
  status: string | null;
  failureCode: string | null;
  replayed: boolean;
}

/** A frame this build cannot render is reported, never guessed at. */
export type ChatStreamEventParse =
  | { ok: true; event: ChatStreamEvent }
  | { ok: false; reason: string; fatal: boolean };

function optionalString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function optionalNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function optionalBoolean(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}

/** Read a checkpoint's payload member-by-member; see {@link DesignCheckpoint}. */
function readCheckpoint(raw: Record<string, unknown>): DesignCheckpoint {
  return {
    documentId: optionalString(raw.document_id),
    version: optionalNumber(raw.version),
    operations: optionalNumber(raw.operations),
    preflightClean: optionalBoolean(raw.preflight_clean),
  };
}

/**
 * The streamed operations, or `null` when the frame carried none this build can
 * read. All-or-nothing on purpose; see {@link DesignOpBatch}.
 */
function readOperations(
  value: unknown,
): readonly Record<string, unknown>[] | null {
  if (!Array.isArray(value) || value.length === 0) return null;
  for (const entry of value) {
    if (entry === null || typeof entry !== "object" || Array.isArray(entry)) {
      return null;
    }
    if (typeof (entry as Record<string, unknown>).kind !== "string") {
      return null;
    }
  }
  return value as readonly Record<string, unknown>[];
}

/** Read an op batch's payload member-by-member; see {@link DesignOpBatch}. */
function readOpBatch(raw: Record<string, unknown>): DesignOpBatch {
  return {
    documentId: optionalString(raw.document_id),
    operations: readOperations(raw.operations),
    operationsTotal: optionalNumber(raw.operations_total),
    iteration: optionalNumber(raw.iteration),
  };
}

/**
 * Parse one SSE `data:` payload into a typed event, cross-checking its SSE
 * ``event:`` discriminator when the wire name is supplied.
 *
 * Failure modes are deliberately split (charter §3.2: "unknown event/part
 * versions fail at the repository boundary … rather than rendering guessed
 * UI"):
 *
 * - a `schema_version` this build does not know is **fatal**: every field
 *   meaning is now in doubt, so the stream stops and the surface says so;
 * - a recognized frame without common project/thread/turn identity is
 *   **fatal**: the repository cannot prove it belongs to this attachment;
 * - a malformed or unknown-typed frame is **non-fatal**: the frame is dropped
 *   and reported, the cursor still advances, and the rest of the turn renders.
 *   Rendering an invented card would be worse than a missing one.
 */
export function parseChatStreamEvent(
  payload: unknown,
  wireEventName?: string | null,
): ChatStreamEventParse {
  const version = (payload as { schema_version?: unknown } | null)
    ?.schema_version;
  if (typeof version === "string" && version !== CHAT_STREAM_SCHEMA_VERSION) {
    return {
      ok: false,
      fatal: true,
      reason: `unsupported turn-stream schema version ${version}`,
    };
  }
  const rawPayload =
    payload !== null && typeof payload === "object"
      ? (payload as Record<string, unknown>)
      : null;
  if (
    version === CHAT_STREAM_SCHEMA_VERSION &&
    ChatStreamEventTypeSchema.safeParse(rawPayload?.type).success &&
    !CommonIdentitySchema.safeParse(payload).success
  ) {
    return {
      ok: false,
      fatal: true,
      reason: "turn-stream frame identity missing",
    };
  }
  const envelope = EnvelopeSchema.safeParse(payload);
  if (!envelope.success) {
    return { ok: false, fatal: false, reason: "malformed turn-stream frame" };
  }
  if (wireEventName !== undefined && wireEventName !== envelope.data.type) {
    return {
      ok: false,
      fatal: true,
      reason: "turn-stream event name/type mismatch",
    };
  }
  const raw = envelope.data as Record<string, unknown>;

  let part: ChatPart | null = null;
  if (raw.part !== undefined && raw.part !== null) {
    const parsed = ChatPartSnapshotSchema.safeParse(raw.part);
    if (!parsed.success) {
      return {
        ok: false,
        fatal: false,
        reason: `unreadable ${envelope.data.part_kind ?? "unknown"} part snapshot`,
      };
    }
    part = parsed.data;
  }

  return {
    ok: true,
    event: {
      schemaVersion: envelope.data.schema_version,
      eventId: envelope.data.event_id ?? null,
      sequence: envelope.data.sequence ?? null,
      occurredAt: envelope.data.occurred_at ?? null,
      projectId: envelope.data.project_id,
      threadId: envelope.data.thread_id,
      turnId: envelope.data.turn_id,
      generationAttemptId: envelope.data.generation_attempt_id ?? null,
      messageId: envelope.data.message_id ?? null,
      partId: envelope.data.part_id ?? null,
      partKind: envelope.data.part_kind ?? null,
      runId: envelope.data.run_id ?? null,
      deltaIndex: envelope.data.delta_index ?? null,
      legId: envelope.data.leg_id ?? null,
      legTurn: raw.leg_turn === true,
      checkpoint:
        envelope.data.type === "design.checkpoint" ? readCheckpoint(raw) : null,
      opBatch:
        envelope.data.type === "design.op_batch" ? readOpBatch(raw) : null,
      type: envelope.data.type,
      part,
      delta: typeof raw.delta === "string" ? raw.delta : null,
      reason: optionalString(raw.reason),
      status: optionalString(raw.status),
      failureCode: optionalString(raw.failure_code),
      replayed: raw.replayed === true,
    },
  };
}

/**
 * An incremental SSE frame reader.
 *
 * `fetch` hands us bytes, not frames: a frame boundary (`\n\n`) lands anywhere,
 * including inside a UTF-8 sequence or between `event:` and `data:`. This keeps
 * the tail of the buffer until a boundary actually arrives, so a delta split
 * across two network chunks is delivered once, whole, and in order.
 */
export interface SseFrame {
  id: string | null;
  event: string | null;
  data: string;
}

export class SseFrameReader {
  private buffer = "";

  /** Feed one decoded chunk; returns every complete frame it closed. */
  push(chunk: string): SseFrame[] {
    this.buffer += chunk.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
    const frames: SseFrame[] = [];
    let boundary = this.buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const block = this.buffer.slice(0, boundary);
      this.buffer = this.buffer.slice(boundary + 2);
      const frame = readFrame(block);
      if (frame) frames.push(frame);
      boundary = this.buffer.indexOf("\n\n");
    }
    return frames;
  }
}

function readFrame(block: string): SseFrame | null {
  let id: string | null = null;
  let event: string | null = null;
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (!line || line.startsWith(":")) continue;
    const separator = line.indexOf(":");
    const field = separator === -1 ? line : line.slice(0, separator);
    const rawValue = separator === -1 ? "" : line.slice(separator + 1);
    const value = rawValue.startsWith(" ") ? rawValue.slice(1) : rawValue;
    if (field === "id") id = value;
    else if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  if (data.length === 0) return null;
  return { id, event, data: data.join("\n") };
}
