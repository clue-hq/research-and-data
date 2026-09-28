"use client";

import { createPortal } from "react-dom";
import { Button } from "@/components/ui/button";
import type { Account } from "../model/account";
import { useAccountPreview } from "../hooks/use-account-preview";
import { ResearchNavigationProvider } from "./research-link";
import { AccountDetailsList, AccountIdentity } from "./account-detail-primitives";
import { AccountPreviewContent, AccountPreviewFrame } from "./account-preview-drawer";
import motion from "./account-motion.module.css";
import styles from "./project-accounts.module.css";

export function ProjectAccountPreview({ account, projectId, onClose }: { account: Account; projectId: string; onClose: () => void }) {
  const { result, retry } = useAccountPreview(account.id, projectId);

  // This preview is opened by a table interaction. Portaling avoids the chat's
  // transformed panels and container queries constraining the fixed drawer.
  return createPortal(
    <ResearchNavigationProvider accountId={account.id} context={{ projectId }}><div className={`${motion.scope} ${styles.previewScope}`}>
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
                  <Button className="mt-3" onClick={retry} size="sm" variant="transparent">Try again</Button>
                </>
              )}
            </div>
          </>
        )}
      </AccountPreviewFrame>
    </div></ResearchNavigationProvider>,
    document.body,
  );
}
