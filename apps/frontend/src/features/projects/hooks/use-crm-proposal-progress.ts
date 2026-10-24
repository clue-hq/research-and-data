"use client";

import { useEffect, useRef, useState } from "react";
import { fetchCrmProposal } from "@/features/integrations/data/crm.repository";
import {
  crmWriteProgressPending,
  type CrmProposalProgress,
} from "@/features/integrations/model/crm-write";
import { usePageVisible } from "./use-page-visible";

/** How often a sending write card re-reads its proposal while the tab shows (card spec §3 B). */
const POLL_VISIBLE_MS = 2000;
/** …and while the tab is hidden (R-12.18): slower, but the card is current when shown again. */
const POLL_HIDDEN_MS = 15000;

/**
 * The progress of a CRM write card's proposal, once the card was answered or withdrawn.
 *
 * Read once when enabled (a declined, replaced or finished card needs it for who answered and
 * why it closed); then re-read after each read returns, while the CRM is still being written to:
 * 2 s later while the tab shows, 15 s later while it is hidden (R-12.18). `wake` is the chat's
 * count of "changes finished" wake-up turns; when it moves, a card still being written to reads at
 * once. A failed read changes nothing; the next tick tries again.
 */
export function useCrmProposalProgress(
  proposalId: string | null,
  enabled: boolean,
  wake = 0,
): CrmProposalProgress | null {
  const [progress, setProgress] = useState<CrmProposalProgress | null>(null);
  const visible = usePageVisible();
  const pending = crmWriteProgressPending(progress);
  const lastWake = useRef(wake);

  useEffect(() => {
    const woke = wake !== lastWake.current;
    lastWake.current = wake;
    if (!enabled || proposalId === null) return;
    if (progress !== null && !pending) return;
    const interval = visible ? POLL_VISIBLE_MS : POLL_HIDDEN_MS;
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
      timer = window.setTimeout(() => void read(), interval);
    };
    if (progress === null || woke) void read();
    else timer = window.setTimeout(() => void read(), interval);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
    // `progress` itself is left out on purpose: the chain reads it once at start, and only its
    // pending-ness, the tab's visibility or a wake-up restarts the chain.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, proposalId, visible, pending, wake]);

  return progress;
}
