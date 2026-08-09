import {
  AcceptedTurnResponseSchema,
  ChatTurnListResponseSchema,
  turnRequestBody,
  type AcceptedTurn,
  type ChatTurnPage,
  type TurnSubmission,
} from "../model/chat-turn";
import { chatRequest, type ChatTransport } from "./chat-api";
import type { FixtureChatState } from "./chat-fixture-state";
import { fixtureTurns } from "./chat.fixture";

/**
 * Turn submission and the §3.5 controls.
 *
 * `submit` posts exactly one of an ordinary message or a structured gate
 * response, always under an `Idempotency-Key`, and returns `202 {turn_id}` —
 * acceptance, not completion. `stop` records a cancellation request for the
 * active generation attempt only; `retry` creates a **new** turn linked to the
 * one it retries and never mutates the prior transcript.
 */
export interface ChatTurnsRepository {
  list(input: { projectId: string; threadId: string }): Promise<ChatTurnPage>;
  submit(input: {
    projectId: string;
    threadId: string;
    submission: TurnSubmission;
    idempotencyKey: string;
  }): Promise<AcceptedTurn>;
  stop(input: {
    projectId: string;
    threadId: string;
    turnId: string;
  }): Promise<{ alreadyRequested: boolean }>;
  retry(input: {
    projectId: string;
    threadId: string;
    turnId: string;
  }): Promise<AcceptedTurn>;
}

function turnsPath(projectId: string, threadId: string, suffix = ""): string {
  return `/projects/${encodeURIComponent(projectId)}/threads/${encodeURIComponent(
    threadId,
  )}/turns${suffix}`;
}

export function createHttpChatTurnsRepository(
  transport: Extract<ChatTransport, { mode: "http" }>,
): ChatTurnsRepository {
  return {
    async list({ projectId, threadId }) {
      return ChatTurnListResponseSchema.parse(
        await chatRequest(transport, turnsPath(projectId, threadId)),
      );
    },
    async submit({ projectId, threadId, submission, idempotencyKey }) {
      return AcceptedTurnResponseSchema.parse(
        await chatRequest(transport, turnsPath(projectId, threadId), {
          method: "POST",
          body: turnRequestBody(submission),
          idempotencyKey,
        }),
      );
    },
    async stop({ projectId, threadId, turnId }) {
      const payload = (await chatRequest(
        transport,
        turnsPath(projectId, threadId, `/${encodeURIComponent(turnId)}/stop`),
        { method: "POST" },
      )) as { data?: { already_requested?: boolean } } | null;
      return { alreadyRequested: payload?.data?.already_requested === true };
    },
    async retry({ projectId, threadId, turnId }) {
      return AcceptedTurnResponseSchema.parse(
        await chatRequest(
          transport,
          turnsPath(projectId, threadId, `/${encodeURIComponent(turnId)}/retry`),
          { method: "POST" },
        ),
      );
    },
  };
}

/**
 * The fixture adapter, holding the thread's submission order in memory.
 *
 * It reproduces the property the rest of the surface depends on: a submitted
 * turn is immediately visible as `queued`, because that is what makes a queued
 * turn renderable at all under the two-phase turn identity.
 */
export function createFixtureChatTurnsRepository(
  state: FixtureChatState,
): ChatTurnsRepository {
  const turns = ChatTurnListResponseSchema.parse({
    data: fixtureTurns,
    meta: {},
  }).turns.slice();
  const accepted = new Map<string, AcceptedTurn>();

  return {
    async list() {
      return {
        turns: [...turns],
        threadRunning: turns.some(
          (turn) => turn.state === "queued" || turn.state === "running",
        ),
      };
    },
    async submit({ projectId, threadId, submission, idempotencyKey }) {
      const existing = accepted.get(idempotencyKey);
      if (existing) return { ...existing, replayed: true };
      const turnId = `local-turn-${turns.length + 1}`;
      if (submission.kind === "gate_response") {
        // The gate answer and the turn are one act, exactly as the real route
        // records them in one transaction.
        state.gateAnswers.set(submission.response.gateId, {
          turnId,
          decision: submission.response.decision,
        });
        state.scripts.set(
          turnId,
          submission.response.decision === "approved" ? "launch" : "turn",
        );
      } else {
        state.scripts.set(turnId, "turn");
      }
      const record: AcceptedTurn = {
        turnId,
        threadId,
        requestedAt: new Date().toISOString(),
        replayed: false,
      };
      accepted.set(idempotencyKey, record);
      turns.push({
        turnId,
        threadId,
        projectId,
        state: "queued",
        requestedAt: record.requestedAt,
        lastEventId: null,
        generationAttempts: 0,
      });
      return record;
    },
    async stop({ turnId }) {
      const turn = turns.find((item) => item.turnId === turnId);
      if (turn) turn.state = "cancelled";
      return { alreadyRequested: false };
    },
    async retry({ projectId, threadId, turnId }) {
      const retryId = `${turnId}-retry`;
      const record: AcceptedTurn = {
        turnId: retryId,
        threadId,
        requestedAt: new Date().toISOString(),
        replayed: false,
      };
      turns.push({
        turnId: retryId,
        threadId,
        projectId,
        state: "queued",
        requestedAt: record.requestedAt,
        lastEventId: null,
        generationAttempts: 0,
      });
      return record;
    },
  };
}
