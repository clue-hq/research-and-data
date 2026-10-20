"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { completeConnection, requestConnectLink } from "../data/crm.repository";
import type { CompleteResponse, CrmProvider } from "../model/crm";

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
      .then(setResult)
      .catch(() => setResult({ outcome: "failed" }));
  }, [requestId, status, connectedAccountId]);

  return result;
}
