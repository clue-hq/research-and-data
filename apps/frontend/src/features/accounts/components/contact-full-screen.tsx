"use client";

import motion from "./account-motion.module.css";
import type { AccountContactDetail } from "../model/account-contact";
import type { AccountDetail } from "../model/account-detail";
import components from "./account-components.module.css";
import { AccountWorkspaceShell } from "./account-workspace-shell";
import { ContactProfileContent } from "./contact-profile-content";

export function ContactFullScreen({
  account,
  contact,
}: {
  account: AccountDetail;
  contact: AccountContactDetail;
}) {
  return (
    <AccountWorkspaceShell
      account={account}
      activeTab="contacts"
      copyLinkLabel="Copy contact link"
      lastModifiedAt={contact.lastModifiedAt}
      showDetailsToggle={false}
    >
      <div className={`${motion.pageEntry} clue-scrollbar-hidden h-full min-h-0 overflow-y-auto`}>
        <article className={components.detailArticle}>
          <ContactProfileContent contact={contact} />
        </article>
      </div>
    </AccountWorkspaceShell>
  );
}
