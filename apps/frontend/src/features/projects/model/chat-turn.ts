import { z } from "zod";
import { GateDecisionSchema } from "./chat-parts";

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

export const LIVE_TURN_STATES: ReadonlySet<TurnState> = new Set([
  "queued",
  "running",
]);

const TurnAcceptedWireSchema = z.object({
  turn_id: z.string().min(1),
  thread_id: z.string().min(1),
  requested_at: z.string(),
  replayed: z.boolean().default(false),
});

export interface AcceptedTurn {
  turnId: string;
  threadId: string;
  requestedAt: string;
  /** True when this idempotency identity had already been accepted. */
  replayed: boolean;
}

export const AcceptedTurnResponseSchema = z
  .object({ data: TurnAcceptedWireSchema })
  .transform(
    (wire): AcceptedTurn => ({
      turnId: wire.data.turn_id,
      threadId: wire.data.thread_id,
      requestedAt: wire.data.requested_at,
      replayed: wire.data.replayed,
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
}

export const ChatTurnListResponseSchema = z
  .object({
    data: z.array(TurnViewWireSchema).default([]),
    meta: z
      .object({ thread_status: z.string().default("idle") })
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
      }),
    ),
    threadRunning: wire.meta.thread_status === "running",
  }));

export type ChatTurnPage = z.infer<typeof ChatTurnListResponseSchema>;

export function isTurnLive(turn: ChatTurn): boolean {
  return LIVE_TURN_STATES.has(turn.state as TurnState);
}

/**
 * The structured gate answer the turn endpoint accepts instead of a message.
 *
 * The two `expected*` fields are the client's statement of *what it was looking
 * at*: the server refuses the answer unless both match the immutable gate. That
 * is what makes "Approve" mean the card that was on the screen. Note what can
 * never appear here on any slice — `actor_id`, `action_ref`, or the amount to
 * *use*: authority is ambient and server-derived.
 */
export const GateResponseSchema = z.object({
  gateId: z.string().min(1),
  decision: GateDecisionSchema,
  expectedSubjectSha256: z.string().regex(/^[0-9a-f]{64}$/),
  expectedEstimatedCostCents: z.number(),
});

export type GateResponse = z.infer<typeof GateResponseSchema>;

export type TurnSubmission =
  | { kind: "message"; message: string }
  | { kind: "gate_response"; response: GateResponse };

/** The wire body of a turn submission. Exactly one of the two, never both. */
export function turnRequestBody(submission: TurnSubmission): unknown {
  if (submission.kind === "message") return { message: submission.message };
  return {
    gate_response: {
      gate_id: submission.response.gateId,
      decision: submission.response.decision,
      expected_subject_sha256: submission.response.expectedSubjectSha256,
      expected_estimated_cost_cents:
        submission.response.expectedEstimatedCostCents,
    },
  };
}
