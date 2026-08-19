"use client";

import { useEffect, useRef, useState } from "react";
import { ClueChatApiError } from "../data/chat-api";
import { useChatRepositories } from "../data/projects-transport";
import type { PolledResearchTask } from "../model/chat-parts";
import type { TranscriptState } from "../model/chat-transcript";
import { researchTaskModel } from "../model/research-task";

/**
 * The 3-second poll that keeps a research-task card honest after its stream
 * ends (Slice C C3, cloned from the email-lookup controller's poll pattern).
 *
 * The turn's SSE stream emits its last task snapshot at turn close; the fleet
 * then works for minutes. This hook re-reads the durable C2 projection while
 * any task is still active or blocked, and stops the moment every task
 * settles — the timer re-arms per completed read, so a slow backend is polled
 * after its response, never on top of it.
 *
 * Two wake conditions, per the plan: the thread loading (which also restores
 * cards lost past the stream-rehydration window), and the stream projecting a
 * task part this poller has not seen (`wake`, the signature below).
 */
export const POLL_DELAY_MS = 3_000;

/** True while any task is moving or waiting on a human — the states worth polling. */
export function hasUnsettledResearchTask(
  tasks: readonly PolledResearchTask[],
): boolean {
  return tasks.some((task) => !researchTaskModel(task.part).terminal);
}

/**
 * A stable fingerprint of *which* task parts the stream has projected.
 *
 * It changes exactly when a `part.created` lands a task part this state did
 * not hold (part ids are deterministic per run), and deliberately ignores
 * revisions — the poller keeps its own cadence while tasks are unsettled, so
 * re-waking on every `part.updated` would buy nothing.
 */
export function streamTaskWakeSignature(stream: TranscriptState): string {
  const ids: string[] = [];
  for (const turn of stream.turns.values()) {
    for (const entry of turn.parts) {
      if (entry.part.kind === "task") ids.push(entry.part.partId);
    }
  }
  return ids.sort().join("\n");
}

export function useResearchTaskPoller({
  projectId,
  threadId,
  enabled,
  wake,
}: {
  projectId: string;
  /** The active thread, or `null` before the route resolves one. */
  threadId: string | null;
  /** False until the conversation loaded (and never true on an access/route refusal). */
  enabled: boolean;
  /** Any value change re-opens polling — see `streamTaskWakeSignature`. */
  wake: string;
}): readonly PolledResearchTask[] {
  const repositories = useChatRepositories();
  const [tasks, setTasks] = useState<readonly PolledResearchTask[]>([]);
  const timeout = useRef<number | null>(null);

  useEffect(() => {
    if (!enabled || threadId === null) return;
    let cancelled = false;
    const clear = () => {
      if (timeout.current !== null) {
        window.clearTimeout(timeout.current);
        timeout.current = null;
      }
    };
    const poll = async () => {
      let next: readonly PolledResearchTask[];
      try {
        next = await repositories.researchTasks.list({ projectId, threadId });
      } catch (error) {
        if (error instanceof ClueChatApiError && error.status === 401) {
          window.location.assign("/sign-in?reason=session_expired");
          return;
        }
        // A durable read that failed changed nothing on screen: keep the last
        // snapshot, stop this cadence, and let the next wake re-open it.
        globalThis.console.error("Research-task poll failed", error);
        return;
      }
      if (cancelled) return;
      setTasks(next);
      if (hasUnsettledResearchTask(next)) {
        timeout.current = window.setTimeout(() => void poll(), POLL_DELAY_MS);
      }
    };
    void poll();
    return () => {
      cancelled = true;
      clear();
    };
  }, [enabled, projectId, repositories, threadId, wake]);

  return tasks;
}
