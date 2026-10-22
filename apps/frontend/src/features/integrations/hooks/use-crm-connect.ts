"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { completeConnection, fetchCrmConnection, requestConnectLink } from "../data/crm.repository";
import {
  CRM_CONNECT_CHANNEL,
  crmConnectionAnswersCard,
  type CompleteResponse,
  type CrmConnectBroadcast,
  type CrmConnectCardModel,
  type CrmConnectedState,
  type CrmProvider,
} from "../model/crm";

/** How often an authorizing card re-reads the connection, when no word comes from the tab. */
const WATCH_INTERVAL_MS = 3000;

/** The connect card's one action: a fresh login link for this card and CRM. */
export function useCrmConnect(): (requestId: string, provider: CrmProvider) => Promise<string> {
  return useCallback(
    (requestId: string, provider: CrmProvider) => requestConnectLink(requestId, provider),
    [],
  );
}

/**
 * The callback page's one action: report the login result to the backend once.
 * `null` while waiting; a missing parameter is a failed login without a request.
 */
export function useCrmCallback(
  requestId: string | null,
  status: string | null,
  connectedAccountId: string | null,
): CompleteResponse | null {
  const complete = Boolean(requestId && status && connectedAccountId);
  const [result, setResult] = useState<CompleteResponse | null>(
    complete ? null : { outcome: "failed" },
  );
  const sent = useRef(false);

  useEffect(() => {
    if (sent.current || !requestId || !status || !connectedAccountId) return;
    sent.current = true;
    completeConnection(requestId, status, connectedAccountId)
      .catch((): CompleteResponse => ({ outcome: "failed" }))
      .then((outcome) => {
        setResult(outcome);
        tellOpenCard({ requestId, outcome: outcome.outcome, provider: outcome.provider ?? null });
      });
  }, [requestId, status, connectedAccountId]);

  return result;
}

/** Tell the chat tab's open connect card how the login ended (same browser only). */
function tellOpenCard(message: CrmConnectBroadcast): void {
  if (typeof BroadcastChannel === "undefined") return;
  const channel = new BroadcastChannel(CRM_CONNECT_CHANNEL);
  channel.postMessage(message);
  channel.close();
}

export interface CrmCardWatch {
  /** The connection that answered this card, once there is one. */
  connected: CrmConnectedState | null;
  /** The CRM whose login failed or was abandoned, when the callback tab said so. */
  failed: CrmProvider | null;
  clearFailure: () => void;
}

/**
 * What the connect card shows is driven by the real connection, never by the click (R-3.10).
 * It reads the connection once (a card reopened after connecting shows as connected), then, while
 * a login is open in another tab, listens for that tab's result and re-reads every few seconds.
 */
export function useCrmCardWatch(
  card: CrmConnectCardModel,
  authorizing: CrmProvider | null,
): CrmCardWatch {
  const [connected, setConnected] = useState<CrmConnectedState | null>(null);
  const [failed, setFailed] = useState<CrmProvider | null>(null);
  // The chat rebuilds the card's object on every render; key the effects on its stable parts.
  const requestId = card.requestId;
  const beforeStatus = card.initialConnection?.status ?? null;
  const beforeAt = card.initialConnection?.connectedAt ?? null;

  useEffect(() => {
    let live = true;
    void answeringConnection(beforeStatus, beforeAt).then((answer) => {
      if (live && answer) setConnected(answer);
    });
    return () => {
      live = false;
    };
  }, [beforeStatus, beforeAt]);

  // The callback tab's word, whenever it comes: a card reloaded mid-login still hears it.
  useEffect(() => {
    if (connected !== null || typeof BroadcastChannel === "undefined") return;
    let live = true;
    const channel = new BroadcastChannel(CRM_CONNECT_CHANNEL);
    channel.onmessage = (event: MessageEvent<CrmConnectBroadcast>) => {
      if (event.data?.requestId !== requestId) return;
      if (event.data.outcome === "failed") {
        setFailed(event.data.provider ?? authorizing);
        return;
      }
      // "connected", or "stale": another click may already have connected it.
      void answeringConnection(beforeStatus, beforeAt).then((answer) => {
        if (live && answer) setConnected(answer);
      });
    };
    return () => {
      live = false;
      channel.close();
    };
  }, [authorizing, requestId, beforeStatus, beforeAt, connected]);

  // While a login is open in another tab, re-read the connection in case no word comes back
  // (the login finished in another browser, or the callback tab was closed early).
  useEffect(() => {
    if (authorizing === null || connected !== null) return;
    let live = true;
    const timer = window.setInterval(() => {
      void answeringConnection(beforeStatus, beforeAt).then((answer) => {
        if (live && answer) setConnected(answer);
      });
    }, WATCH_INTERVAL_MS);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, [authorizing, beforeStatus, beforeAt, connected]);

  return {
    connected,
    failed,
    clearFailure: useCallback(() => setFailed(null), []),
  };
}

/** The connection, when it answers this card; `null` when it does not or cannot be read yet. */
async function answeringConnection(
  beforeStatus: string | null,
  beforeAt: string | null,
): Promise<CrmConnectedState | null> {
  try {
    return crmConnectionAnswersCard(beforeStatus, beforeAt, await fetchCrmConnection());
  } catch {
    return null; // a failed read changes nothing; the next check tries again
  }
}
