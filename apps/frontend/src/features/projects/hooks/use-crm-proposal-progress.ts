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
 * why it closed); then re-read every 2 s while the CRM is still being written to and the tab is
 * showing. A failed read changes nothing; the next tick tries again.
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
    let live = true;
    const read = () =>
      fetchCrmProposal(proposalId)
        .then((next) => {
          if (live) setProgress(next);
        })
        .catch(() => undefined);
    if (progress === null) void read();
    const timer = window.setInterval(() => void read(), POLL_INTERVAL_MS);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
    // `progress` itself is left out on purpose: only its pending-ness restarts the poll.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, proposalId, visible, pending]);

  return progress;
}
