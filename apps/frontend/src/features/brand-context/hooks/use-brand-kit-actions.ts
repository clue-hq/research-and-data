"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  createBrandKitActions,
  type BrandKitActions,
} from "../data/brand-kit-actions";
import {
  approvalChip,
  activeJob,
  canApprove,
  panelEmptyMessage,
  reExtractState,
  type ApprovalChip,
  type BrandKitMeta,
  type IngestionJob,
} from "../model/brand-kit-actions";

/** Only while an ingestion is actually running; the loop stops the moment it is not. */
const POLL_INTERVAL_MS = 3000;

export interface BrandKitActionsController {
  /** The kit's approval state, or `null` when there is no kit to report on. */
  chip: ApprovalChip | null;
  /** Approve is shown for an unapproved kit only — and there is no un-approve, ever. */
  showApprove: boolean;
  approving: boolean;
  approve: () => void;
  approveDisabled: boolean;
  reExtract: () => void;
  reExtractDisabled: boolean;
  /** Why Re-extract cannot fire, for the title/aria-description — `null` when it can. */
  reExtractHint: string | null;
  extracting: boolean;
  colorsEmptyMessage: string;
  typographyEmptyMessage: string;
}

/**
 * Slice 4: the Brand-context page's Approve / Re-extract lifecycle.
 *
 * Every decision it reports is the pure model's (`model/brand-kit-actions`); this hook owns only
 * the three things a pure function cannot: the ingestion-job read, the poll that runs ONLY while
 * a job is in flight, and the `router.refresh()` that re-renders the server component once a run
 * publishes a new version or an approval lands. The page keeps showing the latest PUBLISHED
 * version throughout — nothing here renders a kit that does not exist yet.
 */
export function useBrandKitActions(
  kit: BrandKitMeta | null,
  actionsFactory: () => BrandKitActions = createBrandKitActions,
): BrandKitActionsController {
  const router = useRouter();
  // `null` is not "no jobs". It means the active-job read has not succeeded yet, so both
  // mutations stay fail-closed until we know they cannot race an ingestion.
  const [jobs, setJobs] = useState<readonly IngestionJob[] | null>(null);
  const [approving, setApproving] = useState(false);
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
  const controlsBusy = jobs === null || hasActiveJob || extracting || approving;

  const approve = useCallback(() => {
    if (!canApprove(kit) || approving || controlsBusy || kit === null) return;
    setApproving(true);
    void actions
      .approve(kit.id)
      .then(() => {
        // Re-read the kit from the store rather than assuming the flip: the chip must report
        // what the store says, not what we asked for.
        router.refresh();
      })
      .catch((error: unknown) => {
        console.warn("[brand-context] the approval was refused:", error);
      })
      .finally(() => {
        if (mounted.current) setApproving(false);
      });
  }, [actions, approving, controlsBusy, kit, router]);

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
    approve,
    approveDisabled: controlsBusy,
    approving,
    chip: approvalChip(kit),
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
    showApprove: canApprove(kit),
    typographyEmptyMessage: panelEmptyMessage("typography", jobs ?? []),
  };
}
