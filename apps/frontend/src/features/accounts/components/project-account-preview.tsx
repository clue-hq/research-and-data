"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Button } from "@/components/ui/button";
import type { Account } from "../model/account";
import { AccountDetailResponseSchema, type AccountDetail } from "../model/account-detail";
import { AccountDetailsList, AccountIdentity } from "./account-detail-primitives";
import { AccountPreviewContent, AccountPreviewFrame } from "./account-preview-drawer";
import motion from "./account-motion.module.css";
import styles from "./project-accounts.module.css";

type PreviewResult =
  | { status: "loading" | "missing" | "error" }
  | { status: "ready"; account: AccountDetail };

export function ProjectAccountPreview({ account, onClose }: { account: Account; onClose: () => void }) {
  const [result, setResult] = useState<PreviewResult>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const request = new AbortController();
    async function load() {
      try {
        const response = await fetch(`/api/accounts/${encodeURIComponent(account.id)}`, { signal: request.signal });
        if (response.status === 404) {
          if (!request.signal.aborted) setResult({ status: "missing" });
          return;
        }
        if (!response.ok) throw new Error("Unable to load account details");
        const { data } = AccountDetailResponseSchema.parse(await response.json());
        if (!request.signal.aborted) setResult({ status: "ready", account: data });
      } catch {
        if (!request.signal.aborted) setResult({ status: "error" });
      }
    }
    void load();
    return () => request.abort();
  }, [account.id, attempt]);

  // This preview is opened by a table interaction. Portaling avoids the chat's
  // transformed panels and container queries constraining the fixed drawer.
  return createPortal(
    <div className={`${motion.scope} ${styles.previewScope}`}>
      <AccountPreviewFrame account={result.status === "ready" ? result.account : { ...account, previewTitle: account.name }} onClose={onClose}>
        {result.status === "ready" ? <AccountPreviewContent account={result.account} /> : (
          <>
            <AccountIdentity account={account} />
            <div className="mt-9">
              <AccountDetailsList account={{
                ...account,
                headcountLabel: account.employeeBand,
                revenueLabel: account.revenueBand,
                // The row carries the URL, not the served label; an account with
                // no primary domain reads as the table's own missing-value glyph.
                websiteLabel: account.websiteUrl ? new URL(account.websiteUrl).hostname : "—",
                locationsLabel: account.locationsLabel ?? String(account.locationCount),
                contacts: [],
              }} />
            </div>
            <div aria-live="polite" className="mt-9 text-[var(--clue-content-subtle)]" role={result.status === "error" ? "alert" : "status"}>
              {result.status === "loading" ? "Loading full account details…" : result.status === "missing" ? "Full account details are not available yet." : (
                <>
                  <p>Unable to load full account details.</p>
                  <Button className="mt-3" onClick={() => { setResult({ status: "loading" }); setAttempt((current) => current + 1); }} size="sm" variant="transparent">Try again</Button>
                </>
              )}
            </div>
          </>
        )}
      </AccountPreviewFrame>
    </div>,
    document.body,
  );
}
