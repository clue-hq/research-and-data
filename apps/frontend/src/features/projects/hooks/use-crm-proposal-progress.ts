"use client";

import { useEffect, useState } from "react";
import { fetchCrmProposal } from "@/features/integrations/data/crm.repository";
import {
  crmWriteProgressPending,
  type CrmProposalProgress,
} from "@/features/integrations/model/crm-write";
import { usePageVisible } from "./use-page-visible";

/** How often a sending write card re-reads its proposal (card spec §3 B). */
const POLL_INTERVAL_MS = 2000;

/**
 * The progress of a CRM write card's proposal, once the card was answered or withdrawn.
 *
 * Read once when enabled (a declined, replaced or finished card needs it for who answered and
 * why it closed); then re-read 2 s after each read returns, while the CRM is still being written
 * to and the tab is showing. A failed read changes nothing; the next tick tries again.
 */
export function useCrmProposalProgress(
  proposalId: string | null,
  enabled: boolean,
): CrmProposalProgress | null {
  const [progress, setProgress] = useState<CrmProposalProgress | null>(null);
  const visible = usePageVisible();
  const pending = crmWriteProgressPending(progress);

  useEffect(() => {
    if (!enabled || proposalId === null || !visible) return;
    if (progress !== null && !pending) return;
    // One read at a time: the next is scheduled only after the last one returned, so an older
    // response can never land after a newer one. A response after cleanup is dropped.
    let live = true;
    let timer: number | undefined;
    const read = async () => {
      try {
        const next = await fetchCrmProposal(proposalId);
        if (!live) return;
        setProgress(next);
        if (!crmWriteProgressPending(next)) return;
      } catch {
        if (!live) return; // a failed read changes nothing; the next tick tries again
      }
      timer = window.setTimeout(() => void read(), POLL_INTERVAL_MS);
    };
    if (progress === null) void read();
    else timer = window.setTimeout(() => void read(), POLL_INTERVAL_MS);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
    // `progress` itself is left out on purpose: the chain reads it once at start, and only its
    // pending-ness (or visibility) restarts the chain.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, proposalId, visible, pending]);

  return progress;
}
