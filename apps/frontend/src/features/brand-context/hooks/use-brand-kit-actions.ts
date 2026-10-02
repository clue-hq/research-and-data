"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  createBrandKitActions,
  type BrandKitActions,
} from "../data/brand-kit-actions";
import {
  activeJob,
  panelEmptyMessage,
  reExtractState,
  type BrandKitMeta,
  type IngestionJob,
} from "../model/brand-kit-actions";

/** Only while an ingestion is actually running; the loop stops the moment it is not. */
const POLL_INTERVAL_MS = 3000;

export interface BrandKitActionsController {
  reExtract: () => void;
  reExtractDisabled: boolean;
  /** Why Re-extract cannot fire, for the title/aria-description — `null` when it can. */
  reExtractHint: string | null;
  extracting: boolean;
  colorsEmptyMessage: string;
  typographyEmptyMessage: string;
}

/**
 * The Brand-context page's extraction lifecycle; ingestion approves kits automatically.
 *
 * Every decision it reports is the pure model's (`model/brand-kit-actions`); this hook owns only
 * the three things a pure function cannot: the ingestion-job read, the poll that runs ONLY while
 * a job is in flight, and the `router.refresh()` that re-renders the server component once a run
 * finishes publishing a new version. The page keeps showing the latest PUBLISHED
 * version throughout — nothing here renders a kit that does not exist yet.
 */
export function useBrandKitActions(
  kit: BrandKitMeta | null,
  actionsFactory: () => BrandKitActions = createBrandKitActions,
): BrandKitActionsController {
  const router = useRouter();
  // `null` is not "no jobs". It means the active-job read has not succeeded yet, so
  // re-extraction stays fail-closed until we know it cannot race an ingestion.
  const [jobs, setJobs] = useState<readonly IngestionJob[] | null>(null);
  const [extracting, setExtracting] = useState(false);
  // Fixed for the hook's lifetime: the in-flight guards live inside this object, so replacing it
  // on a re-render would hand a double click two unguarded runners.
  const actionsRef = useRef<BrandKitActions | null>(null);
  if (actionsRef.current === null) actionsRef.current = actionsFactory();
  const actions = actionsRef.current;
  const mounted = useRef(true);
  // The last job state we reported to the server component, so a run that FINISHES triggers
  // exactly one refresh — and a job that stays finished never triggers another.
  const wasActive = useRef(false);

  const readJobs = useCallback(async () => {
    const next = await actions.listIngestionJobs();
    if (!mounted.current) return;
    if (next === null) {
      setJobs(null);
      return;
    }
    setJobs(next);
    const active = activeJob(next) !== null;
    if (wasActive.current && !active) router.refresh();
    wasActive.current = active;
  }, [actions, router]);

  useEffect(() => {
    mounted.current = true;
    void readJobs();
    return () => {
      mounted.current = false;
    };
  }, [readJobs]);

  // Retry an unavailable first read as well as polling a real active job. Controls remain
  // disabled in both cases; the interval stops as soon as a successful terminal/empty read lands.
  const polling = jobs === null || activeJob(jobs) !== null;
  useEffect(() => {
    if (!polling) return;
    const interval = window.setInterval(() => void readJobs(), POLL_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, [polling, readJobs]);

  const hasActiveJob = jobs !== null && activeJob(jobs) !== null;
  const reExtraction = jobs === null ? null : reExtractState(kit, jobs);
  const controlsBusy = jobs === null || hasActiveJob || extracting;

  const reExtract = useCallback(() => {
    if (reExtraction?.kind !== "ready" || controlsBusy) return;
    setExtracting(true);
    void actions
      .reExtract(reExtraction.request)
      .catch((error: unknown) => {
        console.warn("[brand-context] the re-extraction was refused:", error);
      })
      .finally(() => {
        if (mounted.current) setExtracting(false);
        // Whether it was accepted or refused, the job list is the truth about what is running.
        void readJobs();
      });
  }, [actions, controlsBusy, reExtraction, readJobs]);

  return {
    colorsEmptyMessage: panelEmptyMessage("colors", jobs ?? []),
    extracting,
    reExtract,
    reExtractDisabled: reExtraction?.kind !== "ready" || controlsBusy,
    reExtractHint:
      jobs === null
        ? "Checking extraction status"
        : reExtraction?.kind === "unavailable"
        ? "No website on record"
        : reExtraction?.kind === "busy"
          ? "An extraction is already running"
          : null,
    typographyEmptyMessage: panelEmptyMessage("typography", jobs ?? []),
  };
}
