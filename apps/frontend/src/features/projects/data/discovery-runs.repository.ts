import { z } from "zod";
import { chatRequest, type ChatTransport } from "./chat-api";

/**
 * The account-discovery run a project's thread is holding.
 *
 * Only Stop lives here. What run a thread holds, and whether it can still be
 * stopped, is read off the thread list (`ChatThread.discovery`); the run's
 * results reach the conversation through its wake turn, never through this
 * repository.
 */
export interface DiscoveryRunsRepository {
  /**
   * Ask the run to stop. The run ends `stopped` and queues its wake turn, which
   * is what releases the thread — so this receipt says the request was
   * recorded, not that the thread is free.
   */
  stop(input: { projectId: string; runId: string }): Promise<DiscoveryStopReceipt>;
}

const DiscoveryStopResponseSchema = z
  .object({
    data: z.object({ run_id: z.string().min(1), stop_requested: z.boolean() }),
  })
  .transform(({ data }) => ({
    runId: data.run_id,
    stopRequested: data.stop_requested,
  }));

export type DiscoveryStopReceipt = z.infer<typeof DiscoveryStopResponseSchema>;

export function createHttpDiscoveryRunsRepository(
  transport: Extract<ChatTransport, { mode: "http" }>,
): DiscoveryRunsRepository {
  return {
    async stop({ projectId, runId }) {
      return DiscoveryStopResponseSchema.parse(
        await chatRequest(
          transport,
          `/projects/${encodeURIComponent(projectId)}/discovery-runs/${encodeURIComponent(
            runId,
          )}/stop`,
          { method: "POST" },
        ),
      );
    },
  };
}

/** The fixture adapter: no fixture thread holds a discovery, so Stop just acknowledges. */
export function createFixtureDiscoveryRunsRepository(): DiscoveryRunsRepository {
  return {
    async stop({ runId }) {
      return { runId, stopRequested: true };
    },
  };
}
