"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/** Whether any section of a page is still being written by the fleet. */
export function anySectionPending(sections: ReadonlyArray<{ pending?: boolean }>): boolean {
  return sections.some((section) => section.pending === true);
}

/**
 * Re-read the page every `pollMs` while a section is pending (spec 2026-09-12 §4, ruling
 * 2026-09-21). The account pages are server components that fetch once, so the poll is a
 * `router.refresh()`: the server re-reads, the pending sections arrive written, and the
 * placeholder sentence they carried is replaced by their items. Stops as soon as nothing is
 * pending; never runs on a fully written page.
 */
export function usePendingSectionsRefresh(pending: boolean, pollMs = 5000): void {
  const router = useRouter();
  useEffect(() => {
    if (!pending) return;
    const interval = window.setInterval(() => router.refresh(), pollMs);
    return () => window.clearInterval(interval);
  }, [pending, pollMs, router]);
}
