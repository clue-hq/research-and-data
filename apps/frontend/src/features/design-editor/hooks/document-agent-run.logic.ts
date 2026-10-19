import type { DocumentAgentRun } from "../data/document-agent-run";

/** What the standalone editor surface knows about the run driving its document. */
export interface AgentRunPollState {
  active: boolean;
  runId: string | null;
  /** `null` until the first successful read — the first observed version is a
   * baseline, never a change. */
  currentVersion: number | null;
  /** Increments each time `current_version` moves between reads: a checkpoint
   * landed, or the run finished and committed. The surface adds it to the
   * canvas reload token, which is how this route gets the reloads the chat
   * route gets from `design.checkpoint` frames. */
  reloadNonce: number;
}

export const INITIAL_AGENT_RUN_POLL: AgentRunPollState = {
  active: false,
  runId: null,
  currentVersion: null,
  reloadNonce: 0,
};

export function reduceAgentRunPoll(
  previous: AgentRunPollState,
  next: DocumentAgentRun,
): AgentRunPollState {
  const moved =
    previous.currentVersion !== null && next.currentVersion !== previous.currentVersion;
  return {
    active: next.active,
    runId: next.runId,
    currentVersion: next.currentVersion,
    reloadNonce: moved ? previous.reloadNonce + 1 : previous.reloadNonce,
  };
}

/**
 * Whether the standalone route should reload an open SITE when its poll moves (review finding
 * K3-3): for a version past the one the site's save queue already knows (someone else wrote: the
 * agent, another tab), or when the agent's run just ended — never for a version the session wrote
 * itself, whose reload used to push a copy into the canvas while the marketer was still typing.
 * (The working copy ignores a stale load anyway; this also saves the needless read.)
 */
export function siteReloadWanted({
  polledVersion,
  knownVersion,
  runEnded,
}: {
  polledVersion: number | null;
  knownVersion: number | null;
  runEnded: boolean;
}): boolean {
  if (runEnded) return true;
  if (polledVersion === null) return false;
  return knownVersion === null || polledVersion > knownVersion;
}
