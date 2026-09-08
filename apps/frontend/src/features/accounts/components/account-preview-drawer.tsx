"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import type { AccountDetail } from "../model/account-detail";
import { useDrawerTransition } from "../hooks/use-drawer-transition";
import motion from "./account-motion.module.css";
import {
  AccountDetailsList,
  AccountIdentity,
  AccountTextSection,
  PreviewToolbar,
} from "./account-detail-primitives";
import components from "./account-components.module.css";
import { AccountResearchBody } from "./account-research-overview";

export function AccountPreviewDrawer({
  account,
}: {
  account: AccountDetail;
}) {
  const router = useRouter();
  const transition = useDrawerTransition();
  const navigate = (href: string) => {
    router.prefetch(href);
    transition.close(() => router.push(href, { scroll: false }));
  };
  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented) navigate("/accounts");
    };
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  });

  return (
    <aside
      aria-label={`${account.name} account preview`}
      className={`${motion.drawer} ${components.previewDrawer}`}
      data-closing={transition.closing}
      onAnimationEnd={transition.onAnimationEnd}
    >
      <PreviewToolbar account={account} onNavigateTo={navigate} />
      <div className={components.previewContent}>
        <div>
          <AccountIdentity account={account} />
        </div>
        <div className="mt-9">
          <AccountDetailsList account={account} showContacts />
        </div>
        {account.overviewDisplay ? (
          <AccountResearchBody account={account} />
        ) : (
          <>
            {account.summaryParagraphs.length > 0 ? (
              <div className="mt-9">
                <AccountTextSection
                  paragraphs={account.summaryParagraphs}
                  title="Account summary"
                />
              </div>
            ) : null}
            {account.businessParagraphs.length > 0 ? (
              <div className="mt-9">
                <AccountTextSection
                  paragraphs={account.businessParagraphs}
                  title="About their business"
                />
              </div>
            ) : null}
          </>
        )}
      </div>
    </aside>
  );
}
