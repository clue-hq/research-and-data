"use client";

import { useResearchNavigation } from "./research-link";
import { researchHref } from "../model/research-context";
import { useRouter } from "next/navigation";
import { useEffect, useRef, type ReactNode } from "react";
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

export function AccountPreviewFrame({
  account,
  children,
  onClose,
}: {
  account: Pick<AccountDetail, "id" | "name" | "previewTitle">;
  children: ReactNode;
  onClose?: () => void;
}) {
  const router = useRouter();
  const navigation = useResearchNavigation();
  const transition = useDrawerTransition();
  const drawerRef = useRef<HTMLElement>(null);
  const contextual = Boolean(onClose);
  const navigate = (href: string) => {
    const destination = researchHref(href, account.id, navigation?.context);
    router.prefetch(destination);
    transition.close(() => router.push(destination, { scroll: false }));
  };
  const close = () => onClose ? transition.close(onClose) : navigate("/accounts");
  useEffect(() => {
    if (!contextual) return;
    const trigger = document.activeElement;
    drawerRef.current?.querySelector<HTMLElement>('[aria-label="Close account preview"]')?.focus({ preventScroll: true });
    return () => {
      if (trigger instanceof HTMLElement && trigger.isConnected) trigger.focus({ preventScroll: true });
    };
  }, [contextual]);
  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented) {
        event.preventDefault();
        // Close this drawer before the project workspace handles Escape.
        if (contextual) event.stopPropagation();
        close();
      }
    };
    document.addEventListener("keydown", escape, contextual);
    return () => document.removeEventListener("keydown", escape, contextual);
  });

  return (
    <aside
      aria-label={`${account.name} account preview`}
      className={`${motion.drawer} ${components.previewDrawer}`}
      data-closing={transition.closing}
      onAnimationEnd={transition.onAnimationEnd}
      ref={drawerRef}
    >
      <PreviewToolbar account={account} onClose={onClose ? close : undefined} onNavigateTo={navigate} />
      <div className={components.previewContent}>{children}</div>
    </aside>
  );
}

export function AccountPreviewContent({ account }: { account: AccountDetail }) {
  return (
    <>
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
    </>
  );
}

export function AccountPreviewDrawer({ account }: { account: AccountDetail }) {
  return (
    <AccountPreviewFrame account={account}>
      <AccountPreviewContent account={account} />
    </AccountPreviewFrame>
  );
}
