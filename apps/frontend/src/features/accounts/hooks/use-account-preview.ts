"use client";

import { useEffect, useState } from "react";
import type { AccountDetail } from "../model/account-detail";
import { fetchAccountPreview } from "../data/account-preview.repository";

type PreviewResult =
  | { status: "loading" | "missing" | "error" }
  | { status: "ready"; account: AccountDetail };

export function useAccountPreview(accountId: string, projectId: string) {
  const [result, setResult] = useState<PreviewResult>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const request = new AbortController();
    async function load() {
      try {
        const data = await fetchAccountPreview(accountId, { projectId }, request.signal);
        if (data === null) {
          if (!request.signal.aborted) setResult({ status: "missing" });
          return;
        }
        if (!request.signal.aborted) setResult({ status: "ready", account: data });
      } catch {
        if (!request.signal.aborted) setResult({ status: "error" });
      }
    }
    void load();
    return () => request.abort();
  }, [accountId, projectId, attempt]);

  return { result, retry: () => { setResult({ status: "loading" }); setAttempt((current) => current + 1); } };
}
