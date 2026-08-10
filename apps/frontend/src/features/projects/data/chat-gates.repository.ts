import { ChatGateListResponseSchema, type ChatGate } from "../model/chat-gate";
import { ClueChatApiError, chatRequest, type ChatTransport } from "./chat-api";
import type { FixtureChatState } from "./chat-fixture-state";
import { fixtureGates } from "./chat.fixture";

/**
 * The durable gate read behind the approval card.
 *
 * **Contract status — reported, not assumed.** The projection this reads
 * (`clue_projections.gates.thread_gates`, whose docstring says it "is the
 * transcript's question … the shape a `gate` part and the `task` part that
 * follows an approval both read") exists and is complete, but **no HTTP route
 * serves it**: the chat surface's ten endpoints are thread CRUD, messages,
 * turns, the stream, stop and retry. At the same time the `gate` part that does
 * reach the client carries only `gate_ref`, `gate_kind` and `state`, because
 * `conversation_turns.py::_project_turn_close` calls
 * `emit_gate_part(ref=…, gate_kind=…)` and passes nothing else.
 *
 * A gate answer requires `expected_subject_sha256` and
 * `expected_estimated_cost_cents`, and the server refuses anything that does
 * not match the immutable row. So against a real backend today the card can be
 * *shown* and cannot be *answered*. This repository is therefore written
 * against the natural projection of the read that already exists, and its HTTP
 * adapter reports `available: false` rather than inventing a digest or an
 * amount — the card then renders the request with its controls disabled and
 * says exactly why. The gap is in the slice report for founder review; this
 * file does not edit the contract document.
 */
export interface ChatGateRead {
  /** False when this deployment served no durable gate payload. */
  available: boolean;
  gates: readonly ChatGate[];
  /** Why, when it did not. Rendered on the card; never swallowed. */
  reason: string | null;
}

export interface ChatGatesRepository {
  list(input: { projectId: string; threadId: string }): Promise<ChatGateRead>;
}

const UNSERVED =
  "this deployment serves no durable gate read, so the approval card cannot " +
  "send the subject digest the server requires";

export function createHttpChatGatesRepository(
  transport: Extract<ChatTransport, { mode: "http" }>,
): ChatGatesRepository {
  return {
    async list({ projectId, threadId }) {
      try {
        const gates = ChatGateListResponseSchema.parse(
          await chatRequest(
            transport,
            `/projects/${encodeURIComponent(projectId)}/threads/${encodeURIComponent(
              threadId,
            )}/gates`,
          ),
        );
        return { available: true, gates, reason: null };
      } catch (error) {
        // A 404 here is the *route* being absent, not an empty thread: the
        // chat surface answers `THREAD_NOT_FOUND` for a thread it cannot see,
        // and anything else 404 means the endpoint is not mounted. Either way
        // the honest answer is "no payload", never a fabricated one.
        if (error instanceof ClueChatApiError && error.status === 404) {
          return { available: false, gates: [], reason: UNSERVED };
        }
        throw error;
      }
    },
  };
}

export function createFixtureChatGatesRepository(
  state: FixtureChatState,
): ChatGatesRepository {
  const gates = new Map<string, ChatGate>();
  for (const gate of ChatGateListResponseSchema.parse({ data: fixtureGates })) {
    gates.set(gate.gateId, gate);
  }
  return {
    async list({ threadId }) {
      return {
        available: true,
        gates: [...gates.values()]
          .filter((gate) => gate.threadId === threadId)
          .map((gate) => {
            // "Open" is the absence of an answer record, here as on the wire:
            // the answer was written by the turn endpoint, not by this read.
            const answered = state.gateAnswers.get(gate.gateId);
            if (!answered) return gate;
            return {
              ...gate,
              answer: {
                turnId: answered.turnId,
                actionRef: `turn-action:${answered.turnId}`,
                decision: answered.decision,
                answeredByUserId: gate.addresseeUserId,
                answeredAt: new Date().toISOString(),
              },
              launches:
                answered.decision === "approved"
                  ? [
                      {
                        researchRunId: "5b1d2c30-0000-4000-8000-000000000200",
                        runKind: "account_research",
                        runState: "running",
                        sourceActionRef: `turn-action:${answered.turnId}`,
                        approvalRefs: [`turn-action:${answered.turnId}`],
                      },
                    ]
                  : [],
            };
          }),
        reason: null,
      };
    },
  };
}
