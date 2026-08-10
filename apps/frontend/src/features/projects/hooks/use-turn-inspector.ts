"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useChatRepositories } from "../data/projects-transport";
import type {
  ChatInspectorCapability,
  ChatInspectorContext,
  ChatInspectorPlanView,
  ChatInspectorRound,
  ChatInspectorToolsView,
} from "../model/chat-inspector";

/**
 * The dev-lens drawer's controller — capability, selection, and the four reads.
 *
 * Deliberately separate from `useProjectChatController`: the inspector reads
 * nothing the conversation needs and the conversation needs nothing from it, so
 * folding it in would make a development affordance part of the state machine
 * that drives real turns.
 *
 * **Availability is asked for, never configured.** The probe runs once per
 * thread; a deployment that did not register the routes answers 404 and
 * `available` stays false, which is how the affordance disappears in production
 * without any component reading an environment variable. A probe failure is a
 * closed drawer, never a broken conversation — this is a debugging lens and has
 * no business surfacing its plumbing into a transcript.
 *
 * **Everything stale is derived, never reset.** Switching threads or turns does
 * not fire a state-clearing effect; every piece of state carries the scope it
 * belongs to and is simply not read outside it. That is why there is no
 * `setState` in any effect body here — the only writes happen in an async
 * callback once a read has actually returned.
 */

export const INSPECTOR_TABS = ["context", "rounds", "plan", "tools"] as const;
export type InspectorTab = (typeof INSPECTOR_TABS)[number];

export interface InspectorTabData {
  context: ChatInspectorContext | null;
  rounds: readonly ChatInspectorRound[];
  plan: ChatInspectorPlanView | null;
  tools: ChatInspectorToolsView | null;
}

export interface TurnInspectorController {
  available: boolean;
  capability: ChatInspectorCapability | null;
  /** The turn whose drawer is open, or `null`. */
  turnId: string | null;
  tab: InspectorTab;
  /** The current tab's payload once it has been read; `undefined` while reading. */
  data: Partial<InspectorTabData> | undefined;
  error: string | null;
  open(turnId: string): void;
  close(): void;
  setTab(tab: InspectorTab): void;
}

/** A cache/selection key. Scope is *in* the key, so nothing has to be cleared. */
function cacheKey(turnId: string, tab: InspectorTab): string {
  return `${turnId}::${tab}`;
}

export function useTurnInspector({
  projectId,
  threadId,
}: {
  projectId: string;
  threadId: string | null;
}): TurnInspectorController {
  const repositories = useChatRepositories();
  // Each of these carries the scope it was produced for, so a stale value is
  // ignored by derivation rather than erased by an effect.
  const [probe, setProbe] = useState<{
    threadId: string;
    capability: ChatInspectorCapability | null;
  } | null>(null);
  const [selection, setSelection] = useState<{
    threadId: string;
    turnId: string;
  } | null>(null);
  const [tab, setTab] = useState<InspectorTab>("context");
  const [cache, setCache] = useState<Record<string, Partial<InspectorTabData>>>({});
  const [failures, setFailures] = useState<Record<string, string>>({});

  const capability =
    probe !== null && threadId !== null && probe.threadId === threadId
      ? probe.capability
      : null;
  const turnId =
    selection !== null && threadId !== null && selection.threadId === threadId
      ? selection.turnId
      : null;

  useEffect(() => {
    if (threadId === null || (probe !== null && probe.threadId === threadId)) return;
    let cancelled = false;
    void repositories.inspector
      .probe({ projectId, threadId })
      .then((result) => {
        if (cancelled) return;
        setProbe({ threadId, capability: result.available ? result.capability : null });
      })
      .catch(() => {
        // Swallowed on purpose. The only thing a failed probe can mean for the
        // user is "no drawer".
        if (!cancelled) setProbe({ threadId, capability: null });
      });
    return () => {
      cancelled = true;
    };
  }, [probe, projectId, repositories, threadId]);

  const key = turnId === null ? null : cacheKey(turnId, tab);

  useEffect(() => {
    if (threadId === null || turnId === null || key === null) return;
    if (key in cache || key in failures) return;
    let cancelled = false;
    const scope = { projectId, threadId, turnId };
    const read = async (): Promise<Partial<InspectorTabData>> => {
      switch (tab) {
        case "context":
          return { context: await repositories.inspector.context(scope) };
        case "rounds":
          return { rounds: await repositories.inspector.rounds(scope) };
        case "plan":
          return { plan: await repositories.inspector.plan(scope) };
        case "tools":
          return { tools: await repositories.inspector.tools(scope) };
      }
    };
    void read()
      .then((value) => {
        if (!cancelled) setCache((previous) => ({ ...previous, [key]: value }));
      })
      .catch((failure: unknown) => {
        if (cancelled) return;
        setFailures((previous) => ({
          ...previous,
          [key]:
            failure instanceof Error ? failure.message : "the inspector read failed",
        }));
      });
    return () => {
      cancelled = true;
    };
  }, [cache, failures, key, projectId, repositories, tab, threadId, turnId]);

  const open = useCallback(
    (next: string) => {
      if (threadId === null) return;
      setSelection({ threadId, turnId: next });
    },
    [threadId],
  );
  const close = useCallback(() => setSelection(null), []);

  return useMemo(
    () => ({
      available: capability !== null,
      capability,
      turnId,
      tab,
      data: key === null ? undefined : cache[key],
      error: key === null ? null : (failures[key] ?? null),
      open,
      close,
      setTab,
    }),
    [cache, capability, close, failures, key, open, tab, turnId],
  );
}
