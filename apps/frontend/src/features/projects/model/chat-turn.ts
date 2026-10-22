import { z } from "zod";
import { GateDecisionSchema } from "./chat-parts";
import type { ChatAttachmentRef } from "./chat-attachments";
import type { ChatStreamEventType } from "./chat-events";
import {
  ChatMessageWireSchema,
  toChatMessage,
  type ChatMessage,
} from "./chat-message";

/**
 * Turn submission and the submissions-union read (charter §3.5, as-built D2).
 *
 * The two-phase turn identity ratified after D2 is the thing to hold on to: a
 * turn that has been accepted but not yet executed exists only as a
 * *submission* row, so `GET …/turns` unions submissions with turn events. A
 * surface built on executed turns alone would show a user's three waiting
 * questions as nothing at all — which is exactly the "visibly queued" the
 * charter demands of the composer.
 */

/** What the submissions-union says about one turn. `queued` counts as busy. */
export const TurnStateSchema = z.enum([
  "queued",
  "running",
  "completed",
  "awaiting_input",
  "failed",
  "cancelled",
]);

export type TurnState = z.infer<typeof TurnStateSchema>;

export const QueueControlSchema = z.object({
  paused: z.boolean(),
  hold_control_id: z.string().nullable(),
  paused_at: z.string().nullable(),
}).transform((wire) => ({ paused: wire.paused, holdControlId: wire.hold_control_id, pausedAt: wire.paused_at }));

export type QueueControl = z.infer<typeof QueueControlSchema>;
export const EMPTY_QUEUE_CONTROL: QueueControl = { paused: false, holdControlId: null, pausedAt: null };

const StopRequestSchema = z.object({
  control_id: z.string().min(1), requested_at: z.string(), pending: z.boolean(),
}).transform((wire) => ({ controlId: wire.control_id, requestedAt: wire.requested_at, pending: wire.pending }));

export const StopTurnResponseSchema = z.object({ data: z.object({
  turn_id: z.string().min(1), control_id: z.string().min(1),
  requested_at: z.string(), already_requested: z.boolean(),
}) }).transform(({ data }) => ({ turnId: data.turn_id, controlId: data.control_id,
  requestedAt: data.requested_at, alreadyRequested: data.already_requested }));

export const ResumeQueueResponseSchema = z.object({ data: z.object({
  hold_control_id: z.string().min(1), replayed: z.boolean(),
  dispatched_turn_id: z.string().nullable(), queue_control: QueueControlSchema,
}) }).transform(({ data }) => ({ holdControlId: data.hold_control_id, replayed: data.replayed,
  dispatchedTurnId: data.dispatched_turn_id, queueControl: data.queue_control }));

export type StopTurnReceipt = z.infer<typeof StopTurnResponseSchema>;
export type ResumeQueueReceipt = z.infer<typeof ResumeQueueResponseSchema>;

export const LIVE_TURN_STATES: ReadonlySet<TurnState> = new Set([
  "queued",
  "running",
]);

const TurnAcceptedWireSchema = z.object({
  turn_id: z.string().min(1),
  thread_id: z.string().min(1),
  requested_at: z.string(),
  replayed: z.boolean().default(false),
  agent_reply: z.enum(["expected", "none"]).default("expected"),
});

export interface AcceptedTurn {
  turnId: string;
  threadId: string;
  requestedAt: string;
  /** True when this idempotency identity had already been accepted. */
  replayed: boolean;
  /**
   * `none` when the submission was recorded and no turn will run for it (the
   * answer to a CRM write card, R-11.6): nothing to attach, nothing in flight.
   */
  agentReply: "expected" | "none";
}

export const AcceptedTurnResponseSchema = z
  .object({ data: TurnAcceptedWireSchema })
  .transform(
    (wire): AcceptedTurn => ({
      turnId: wire.data.turn_id,
      threadId: wire.data.thread_id,
      requestedAt: wire.data.requested_at,
      replayed: wire.data.replayed,
      agentReply: wire.data.agent_reply,
    }),
  );

const TurnViewWireSchema = z.object({
  turn_id: z.string().min(1),
  thread_id: z.string().min(1),
  project_id: z.string().min(1),
  // Open on purpose: the union's state vocabulary is a backend derivation, and
  // a value this build has not been taught is reported as-is rather than
  // dropping the turn out of the transcript.
  state: z.string(),
  requested_at: z.string(),
  last_event_id: z.number().int().nullable().default(null),
  generation_attempts: z.number().int().min(0).default(0),
  submission_message: ChatMessageWireSchema.nullable().default(null),
  derivation: z.string().nullable().default(null),
  answered_gate_id: z.string().nullable().default(null),
  stop_request: StopRequestSchema.nullable().default(null),
});

export interface ChatTurn {
  turnId: string;
  threadId: string;
  projectId: string;
  state: string;
  requestedAt: string;
  /** The stream cursor to attach *after*, so a cold load never replays history. */
  lastEventId: number | null;
  generationAttempts: number;
  /** Accepted user bytes not yet materialized into canonical thread history. */
  submissionMessage: ChatMessage | null;
  /**
   * Non-null when the server made this turn from the user's own message (a design-leg
   * redelivery or first turn): the transcript renders no user bubble for it.
   */
  derivation: string | null;
  /**
   * The agent gate this turn answered (R-11.4): answering a card shows only on the card, so the
   * transcript renders no user bubble for this turn. Absent on turns built before the field.
   */
  answeredGateId?: string | null;
  stopRequest?: z.infer<typeof StopRequestSchema> | null;
}

export const ChatTurnListResponseSchema = z
  .object({
    data: z.array(TurnViewWireSchema).default([]),
    meta: z
      .object({ thread_status: z.string().default("idle"), queue_control: QueueControlSchema.optional() })
      .default({ thread_status: "idle" }),
  })
  .transform((wire) => ({
    turns: wire.data.map(
      (item): ChatTurn => ({
        turnId: item.turn_id,
        threadId: item.thread_id,
        projectId: item.project_id,
        state: item.state,
        requestedAt: item.requested_at,
        lastEventId: item.last_event_id,
        generationAttempts: item.generation_attempts,
        stopRequest: item.stop_request,
        derivation: item.derivation,
        answeredGateId: item.answered_gate_id,
        submissionMessage:
          item.submission_message === null
            ? null
            : toChatMessage(item.submission_message),
      }),
    ),
    threadRunning: wire.meta.thread_status === "running",
    queueControl: wire.meta.queue_control ?? EMPTY_QUEUE_CONTROL,
  }));

export type ChatTurnPage = z.infer<typeof ChatTurnListResponseSchema>;

const TERMINAL_TURN_STATES: ReadonlySet<TurnState> = new Set([
  "completed",
  "awaiting_input",
  "failed",
  "cancelled",
]);

export interface TurnQueueState {
  threadBusy: boolean;
  runningTurn: ChatTurn | null;
  queuedTurns: readonly ChatTurn[];
}

/** The three independent selectors that drive queue and Stop presentation. */
export function selectTurnQueueState(
  turns: readonly ChatTurn[],
): TurnQueueState {
  const runningTurn = turns.find((turn) => turn.state === "running") ?? null;
  const queuedTurns = turns.filter((turn) => turn.state === "queued");
  return {
    threadBusy: runningTurn !== null || queuedTurns.length > 0,
    runningTurn,
    // `GET …/turns` is already in durable submission order; filtering keeps it.
    queuedTurns,
  };
}

export function isTerminalTurnState(state: string): state is TurnState {
  return TERMINAL_TURN_STATES.has(state as TurnState);
}

/**
 * Apply stream-authoritative transitions over a potentially stale list read.
 *
 * A terminal frame must hide Stop on the same render even if an older list
 * request returns `running` afterwards. A `turn.started` frame likewise owns
 * the running target until the canonical read catches up.
 */
export function applyTurnStateOverrides(
  turns: readonly ChatTurn[],
  overrides: ReadonlyMap<string, TurnState>,
): ChatTurn[] {
  return turns.map((turn) => {
    const state = overrides.get(turn.turnId);
    return state === undefined || state === turn.state ? turn : { ...turn, state };
  });
}

/** Drop a stream override once the durable read has reached or passed it. */
export function reconcileTurnStateOverrides(
  overrides: ReadonlyMap<string, TurnState>,
  durableTurns: readonly ChatTurn[],
): ReadonlyMap<string, TurnState> {
  if (overrides.size === 0) return overrides;
  const durable = new Map(durableTurns.map((turn) => [turn.turnId, turn.state]));
  const next = new Map(overrides);
  for (const [turnId, state] of overrides) {
    const durableState = durable.get(turnId);
    if (
      durableState === state ||
      (durableState !== undefined && isTerminalTurnState(durableState)) ||
      (state === "queued" && durableState === "running")
    ) {
      next.delete(turnId);
    }
  }
  return next.size === overrides.size ? overrides : next;
}

export interface MessageSubmissionAttempt {
  fingerprint: string;
  idempotencyKey: string;
}

export type TurnContextObjectType =
  | "account"
  | "contact"
  | "project_document"
  | "design_document"
  | "design_node"
  | "design_asset";

export interface TurnContextReference {
  objectId: string;
  objectType: TurnContextObjectType;
  version: number | null;
  /** Slice 2 (R-A2): the marketer's own words about THIS object — the note a
   * web annotation carries, numbered so the turn's prose ("annotation 2") and
   * the badge in the canvas name the same element. Optional and omitted from
   * the wire when absent, so every existing ref shape is byte-identical. */
  note?: string;
}

/** Block only a duplicate of the exact message request currently in flight. */
export class MessageSubmissionGuard {
  private readonly inFlight = new Map<string, MessageSubmissionAttempt>();

  begin(
    threadId: string,
    submission: {
      message: string;
      contextRefs: readonly TurnContextReference[];
      attachmentRefs: readonly ChatAttachmentRef[];
      agentProfileId: string | null;
    },
    createIdempotencyKey: () => string,
  ): MessageSubmissionAttempt | null {
    const fingerprint = JSON.stringify([threadId, submission]);
    if (this.inFlight.has(fingerprint)) return null;
    const attempt = {
      fingerprint,
      idempotencyKey: createIdempotencyKey(),
    };
    this.inFlight.set(fingerprint, attempt);
    return attempt;
  }

  finish(attempt: MessageSubmissionAttempt): void {
    const current = this.inFlight.get(attempt.fingerprint);
    if (current?.idempotencyKey === attempt.idempotencyKey) {
      this.inFlight.delete(attempt.fingerprint);
    }
  }
}

export function isTurnLive(turn: ChatTurn): boolean {
  return LIVE_TURN_STATES.has(turn.state as TurnState);
}

/** The durable stream transitions that immediately refine the submissions read. */
export function turnStateForStreamEvent(
  type: ChatStreamEventType,
): TurnState | null {
  switch (type) {
    case "turn.accepted":
      return "queued";
    case "turn.started":
    case "turn.retrying":
      return "running";
    case "turn.completed":
      return "completed";
    case "turn.failed":
      return "failed";
    case "turn.cancelled":
      return "cancelled";
    case "turn.awaiting_input":
      return "awaiting_input";
    default:
      return null;
  }
}

/**
 * The structured gate answer the turn endpoint accepts instead of a message.
 *
 * The expected digest is the client's statement of *what it was looking at*.
 * Spend-bearing gates also echo the displayed amount; non-spend gates send
 * null. The server refuses stale authority. That is what makes "Approve" mean
 * the card that was on the screen. Note what can
 * never appear here on any slice — `actor_id`, `action_ref`, or the amount to
 * *use*: authority is ambient and server-derived.
 */
export const GateResponseSchema = z
  .object({
    gateId: z.string().min(1),
    decision: GateDecisionSchema,
    expectedSubjectSha256: z.string().regex(/^[0-9a-f]{64}$/),
    expectedEstimatedCostCents: z.number().nullable(),
    revisionRequest: z.string().min(1).optional(),
    selectedProductId: z.string().min(1).optional(),
    // The set-valued product gate (O6/D10) answers with the whole chosen list.
    // The route refuses `selected_product_id` on that kind and this list on the
    // single-valued one, so the two are never both present here either.
    selectedProductIds: z.array(z.string().min(1)).min(1).readonly().optional(),
    // A CRM write permission card's Allow: the ticked changes and the "Always allow" scopes.
    // Sent as `crm_write`; "Don't allow" sends nothing but the decision.
    crmWrite: z
      .object({
        selected_write_ids: z.array(z.string().min(1)).min(1),
        always_allow: z.array(z.string().min(1)),
      })
      .optional(),
  })
  .superRefine((response, ctx) => {
    const exclusive = [
      response.revisionRequest,
      response.selectedProductId,
      response.selectedProductIds,
      response.crmWrite,
    ].filter((value) => value !== undefined);
    if (exclusive.length > 1) {
      ctx.addIssue({
        code: "custom",
        message:
          "revisionRequest, selectedProductId, selectedProductIds and crmWrite are mutually exclusive",
      });
    }
  });

export type GateResponse = z.infer<typeof GateResponseSchema>;

export type TurnSubmission =
  | {
      kind: "message";
      message: string;
      contextRefs?: readonly TurnContextReference[];
      attachmentRefs?: readonly ChatAttachmentRef[];
      agentProfileId?: string | null;
    }
  | { kind: "gate_response"; response: GateResponse };

/** The wire body of a turn submission. Exactly one of the two, never both. */
export function turnRequestBody(submission: TurnSubmission): unknown {
  if (submission.kind === "message") {
    return {
      message: submission.message,
      context_refs: (submission.contextRefs ?? []).map((reference) => ({
        object_type: reference.objectType,
        object_id: reference.objectId,
        version: reference.version,
        ...(reference.note !== undefined ? { note: reference.note } : {}),
      })),
      attachment_refs: (submission.attachmentRefs ?? []).map((attachment) => ({
        upload_id: attachment.uploadId,
        artifact_key: attachment.artifactKey,
        sha256: attachment.sha256,
        media_type: attachment.mediaType,
        byte_count: attachment.byteCount,
        filename: attachment.filename,
      })),
      agent_profile_id: submission.agentProfileId ?? null,
    };
  }
  const gateResponse: Record<string, unknown> = {
    gate_id: submission.response.gateId,
    decision: submission.response.decision,
    expected_subject_sha256: submission.response.expectedSubjectSha256,
    expected_estimated_cost_cents:
      submission.response.expectedEstimatedCostCents,
  };
  if (submission.response.revisionRequest !== undefined) {
    gateResponse.revision_request = submission.response.revisionRequest;
  }
  if (submission.response.selectedProductId !== undefined) {
    gateResponse.selected_product_id = submission.response.selectedProductId;
  }
  if (submission.response.selectedProductIds !== undefined) {
    gateResponse.selected_product_ids = [...submission.response.selectedProductIds];
  }
  if (submission.response.crmWrite !== undefined) {
    gateResponse.crm_write = {
      selected_write_ids: [...submission.response.crmWrite.selected_write_ids],
      always_allow: [...submission.response.crmWrite.always_allow],
    };
  }
  return {
    gate_response: gateResponse,
  };
}
