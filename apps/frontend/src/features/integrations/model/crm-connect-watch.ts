import type { CrmConnectBroadcast, CrmProvider } from "./crm";

/**
 * What `useCrmConnectionWatch` runs, decided outside React so it can be tested: with no request
 * nothing runs; with one it reads the connection and hears the callback tab until connected, and
 * re-reads on a timer only while a sign-in window is open.
 */
export function crmWatchPlan(
  requestId: string | null,
  authorizing: CrmProvider | null,
  connected: boolean,
): { read: boolean; listen: boolean; poll: boolean } {
  if (requestId === null) return { read: false, listen: false, poll: false };
  return { read: true, listen: !connected, poll: !connected && authorizing !== null };
}

/** The callback tab's word for this request: "failed", or re-read the connection ("connected"/"stale"). */
export function crmWatchMessage(
  data: CrmConnectBroadcast | undefined,
  requestId: string,
): "ignore" | "failed" | "reread" {
  if (data?.requestId !== requestId) return "ignore";
  return data.outcome === "failed" ? "failed" : "reread";
}
