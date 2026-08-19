import {
  ResearchTaskListResponseSchema,
  type PolledResearchTask,
} from "../model/chat-parts";
import { ClueChatApiError, chatRequest, type ChatTransport } from "./chat-api";

/**
 * The durable research-task read the progress card polls (Slice C C2/C3).
 *
 * The turn's SSE stream emits one task snapshot at turn close and then ends,
 * while the fleet works for minutes afterwards. This read serves the same task
 * shape the stream emitted — built by the same backend projection — plus the
 * job-event ledger `revision` the transcript merge orders by, so a polled
 * snapshot and a streamed one are one card, never two.
 */
export interface ChatResearchTasksRepository {
  /**
   * Every research run this thread's turns launched, oldest first. An empty
   * list is the honest answer for a thread that launched nothing — the C2
   * route never 404s a visible thread for having no runs.
   */
  list(input: {
    projectId: string;
    threadId: string;
  }): Promise<readonly PolledResearchTask[]>;
}

export function createHttpChatResearchTasksRepository(
  transport: Extract<ChatTransport, { mode: "http" }>,
): ChatResearchTasksRepository {
  return {
    async list({ projectId, threadId }) {
      try {
        return ResearchTaskListResponseSchema.parse(
          await chatRequest(
            transport,
            `/projects/${encodeURIComponent(projectId)}/threads/${encodeURIComponent(
              threadId,
            )}/research-tasks`,
          ),
        );
      } catch (error) {
        // A 404 is the *route* being absent (a deployment predating C2), not an
        // empty thread — the mounted route answers an empty list for that. The
        // poller then simply has nothing to merge, which is the pre-C3 world.
        if (error instanceof ClueChatApiError && error.status === 404) {
          return [];
        }
        throw error;
      }
    },
  };
}

/**
 * Fixture adapter: no polled tasks. The fixture stream already carries live
 * task parts through their whole lifecycle, so the demo's cards advance on
 * stream frames alone; an empty poll merges as a no-op and can never regress
 * them.
 */
export function createFixtureChatResearchTasksRepository(): ChatResearchTasksRepository {
  return {
    async list() {
      return [];
    },
  };
}
