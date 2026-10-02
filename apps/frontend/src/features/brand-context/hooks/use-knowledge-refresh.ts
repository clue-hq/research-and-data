"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef } from "react";

import { OnboardingStatusSchema, onboardingRunIsLive, type OnboardingStatus } from "../model/brand-knowledge";

const BFF_PATH = "/api/clue/frontend/v1/brand-context/onboarding/current";
const DEFAULT_INTERVAL_MS = 5000;
const MAX_CONSECUTIVE_REFUSALS = 3;

export interface KnowledgeRefreshSource {
  read(): Promise<OnboardingStatus | null>;
}

/** The browser path: the same-origin BFF proves the session and stamps the workspace. */
export const httpKnowledgeRefreshSource: KnowledgeRefreshSource = {
  async read() {
    try {
      const response = await fetch(BFF_PATH, { cache: "no-store" });
      if (!response.ok) return null;
      return OnboardingStatusSchema.parse(await response.json());
    } catch {
      return null;
    }
  },
};

function finishedCount(status: OnboardingStatus | null): number {
  return status?.steps.filter((step) => step.finishedAt !== null).length ?? 0;
}

/** Refresh when a step landed since the last observation, or when the run just went terminal. */
export function shouldRefresh(previous: OnboardingStatus | null, next: OnboardingStatus | null): boolean {
  if (next === null) return false;
  if (finishedCount(next) > finishedCount(previous)) return true;
  return onboardingRunIsLive(previous) && !onboardingRunIsLive(next);
}

/**
 * Progressive fill (ARV2-ONBOARDING-PLAN.md §7): while an onboarding run is queued or running,
 * poll its status and re-render the server page whenever a step finishes, so documents appear
 * as the run publishes them. No progress UI — the dummy has no slot for one.
 *
 * The loop is armed by the run's LIVENESS, not by the `initial` object: `router.refresh()`
 * hands the client a fresh snapshot on every landed step, and re-arming on each of those would
 * restart the timer under its own success. The last observation lives in a ref that survives
 * those re-renders, so a step is never counted twice. The default transport and interval are
 * module constants, so the real mount's dependency list is stable.
 */
export function useKnowledgeRefresh({
  initial,
  source = httpKnowledgeRefreshSource,
  intervalMs = DEFAULT_INTERVAL_MS,
  refresh,
}: {
  initial: OnboardingStatus | null;
  source?: KnowledgeRefreshSource;
  intervalMs?: number;
  refresh?: () => void;
}): void {
  const router = useRouter();
  const last = useRef<OnboardingStatus | null>(initial);
  const refusals = useRef(0);
  const isLive = onboardingRunIsLive(initial);

  useEffect(() => {
    if (!isLive) return;
    let interval: number | null = null;
    const stop = () => {
      if (interval !== null) window.clearInterval(interval);
      interval = null;
    };
    const poll = async () => {
      const next = await source.read();
      if (next === null) {
        // A refused read is not evidence about the run — tolerate a few, then give up rather
        // than hammer a surface that is not answering.
        refusals.current += 1;
        if (refusals.current >= MAX_CONSECUTIVE_REFUSALS) stop();
        return;
      }
      refusals.current = 0;
      if (shouldRefresh(last.current, next)) (refresh ?? (() => router.refresh()))();
      last.current = next;
      if (!onboardingRunIsLive(next)) stop();
    };
    interval = window.setInterval(() => void poll(), intervalMs);
    return stop;
  }, [intervalMs, isLive, refresh, router, source]);
}
