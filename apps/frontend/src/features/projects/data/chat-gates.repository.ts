import { ChatGateListResponseSchema, type ChatGate } from "../model/chat-gate";
import { ClueChatApiError, chatRequest, type ChatTransport } from "./chat-api";
import type { FixtureChatState } from "./chat-fixture-state";
import { fixtureGates } from "./chat.fixture";

/**
 * The durable gate read behind the approval card.
 *
 * The HTTP route serves the persisted `agent_gate` projection, including the
 * exact subject revision/digest, stored decision vocabulary and immutable
 * answer receipt. A streamed `gate` part is only a reference; this durable read
 * is the authority the card validates before rendering controls.
 *
 * Slice 2 intentionally leaves the new ICP gate non-interactive in this client:
 * its Approve/Reject/Revise form (especially the required Revise text) lands in
 * Slice 3. The repository still returns the durable payload now, allowing the
 * renderer to distinguish that supported authority object from malformed,
 * model-only or unavailable references without inventing any gate fields.
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
                expectedSubjectSha256: gate.expectedSubjectSha256,
                decisionPayload: {},
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
