"use client";

import { useEffect, useRef } from "react";

/**
 * Conversation naming, frontend half (spec 2026-09-18-conversation-naming-design §4.7).
 *
 * The backend names an untitled chat (and an untitled project) after the first completed
 * turn, usually before the terminal turn event — and the controller's existing invalidate on
 * that event shows the names. A naming call slower than the engine's grace lands AFTER the
 * event, so while a placeholder is still visible we refetch a bounded number of times and
 * stop the moment both names are present. Only first turns ever poll.
 */
export const NAMING_CATCH_UP_INTERVAL_MS = 5_000;
export const NAMING_CATCH_UP_MAX_TICKS = 12;

export interface NamingCatchUpSchedule {
  intervalMs: number;
  maxTicks: number;
}

/** Pure: what to schedule for this (pending, terminal-revision) pair, or nothing. */
export function namingCatchUpSchedule({
  namingPending,
  terminalRevision,
}: {
  namingPending: boolean;
  terminalRevision: number;
}): NamingCatchUpSchedule | null {
  if (terminalRevision === 0 || !namingPending) return null;
  return { intervalMs: NAMING_CATCH_UP_INTERVAL_MS, maxTicks: NAMING_CATCH_UP_MAX_TICKS };
}

export function useNamingCatchUp({
  namingPending,
  terminalRevision,
  tick,
}: {
  /** True while the active chat has no title or the project is still "Untitled project". */
  namingPending: boolean;
  /** Increments on every terminal turn event of the active thread. */
  terminalRevision: number;
  /** One refetch: invalidate the catalog and reload the thread list. */
  tick: () => void;
}): void {
  // The latest callback, held in a ref so a re-rendered `tick` closure never
  // restarts the interval. Written in an effect, never during render
  // (`react-hooks/refs`).
  const tickRef = useRef(tick);
  useEffect(() => {
    tickRef.current = tick;
  }, [tick]);
  useEffect(() => {
    const schedule = namingCatchUpSchedule({ namingPending, terminalRevision });
    if (schedule === null) return;
    let ticks = 0;
    const handle = setInterval(() => {
      ticks += 1;
      tickRef.current();
      if (ticks >= schedule.maxTicks) clearInterval(handle);
    }, schedule.intervalMs);
    return () => clearInterval(handle);
    // `namingPending` flipping to false clears the interval through the cleanup above.
  }, [namingPending, terminalRevision]);
}
