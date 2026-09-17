import { useEffect, useState } from "react";
import { designBffConfig } from "../data/design-bff";
import { fetchDocumentAgentRun } from "../data/document-agent-run";
import {
  INITIAL_AGENT_RUN_POLL,
  reduceAgentRunPoll,
  type AgentRunPollState,
} from "./document-agent-run.logic";

const DEFAULT_INTERVAL_MS = 4000;

/**
 * Poll the document-scoped agent-busy read for the standalone artifact route
 * (ruling R2: poll, not push — this route has no turn stream). Polls only while
 * enabled and the tab is visible; the first read fires immediately; a failed read
 * keeps the last answer (the lock errs toward what it last knew, and the next
 * tick retries). State resets when the document changes.
 *
 * The reset is STAMPED and DERIVED, never set synchronously in an effect
 * (`react-hooks/set-state-in-effect` forbids that form) — the same idiom
 * `useSceneAssetLibrary` and `useCustomComponentArtifact` use: the poll state
 * carries the document it was read for, and a different (or disabled) document
 * derives the initial state instead. So a switched artifact can never be shown
 * the previous document's lock.
 */
export function useDocumentAgentRun({
  documentId,
  enabled,
  intervalMs = DEFAULT_INTERVAL_MS,
}: {
  documentId: string | null;
  enabled: boolean;
  intervalMs?: number;
}): AgentRunPollState {
  const [stamped, setStamped] = useState<{
    forDocumentId: string | null;
    state: AgentRunPollState;
  }>({ forDocumentId: null, state: INITIAL_AGENT_RUN_POLL });

  useEffect(() => {
    if (!enabled || !documentId) {
      return;
    }
    let cancelled = false;
    let interval: number | null = null;
    const config = designBffConfig();

    const poll = async () => {
      if (typeof document !== "undefined" && document.visibilityState !== "visible") {
        return;
      }
      try {
        const next = await fetchDocumentAgentRun(config, documentId);
        if (!cancelled) {
          setStamped((previous) => ({
            forDocumentId: documentId,
            state: reduceAgentRunPoll(
              previous.forDocumentId === documentId
                ? previous.state
                : INITIAL_AGENT_RUN_POLL,
              next,
            ),
          }));
        }
      } catch {
        // Keep the last answer; the next tick retries.
      }
    };

    void poll();
    interval = window.setInterval(() => void poll(), intervalMs);
    const onVisible = () => {
      if (document.visibilityState === "visible") void poll();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      if (interval !== null) window.clearInterval(interval);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [documentId, enabled, intervalMs]);

  return enabled && documentId !== null && stamped.forDocumentId === documentId
    ? stamped.state
    : INITIAL_AGENT_RUN_POLL;
}
