import Link from "./research-link";
import { ArrowRight } from "lucide-react";
import type { AccountDetail } from "../model/account-detail";
import readability from "./account-readability.module.css";
import components from "./account-components.module.css";
import styles from "./account-research.module.css";
import { AccountIdentity } from "./account-detail-primitives";
import {
  BuyingCommitteeTable,
  ResearchOverview,
} from "./research-content";

export function AccountResearchOverview({
  account,
}: {
  account: AccountDetail;
}) {
  return (
    <div>
      <AccountIdentity account={account} />
      <AccountResearchBody account={account} />
    </div>
  );
}

// Full-page and preview research intentionally share labels, copy and citations.
export function AccountResearchBody({ account }: { account: AccountDetail }) {
  // Watch-outs remain in the research data and Insights' internal notes,
  // but are intentionally omitted from the overview and its preview.
  const sections = (account.overviewDisplay?.sections ?? []).filter(
    (section) => section.key !== "watch-outs",
  );
  // The committee is a TABLE built from `account.buyingCommittee`, never prose.
  // Contract v1 serves a `buying-committee` section in the overview block; that
  // slot renders the table and the section's own generated items are dropped, so
  // the served block never renders as an ordinary section. A block that omits
  // the section (the design build's own fixture predates it) keeps the table
  // where the design put it: immediately before `how-to-approach`.
  const servedCommitteeIndex = sections.findIndex(
    (section) => section.key === "buying-committee",
  );
  const committeeIndex =
    servedCommitteeIndex === -1
      ? sections.findIndex((section) => section.key === "how-to-approach")
      : servedCommitteeIndex;
  const sectionsBeforeCommittee =
    committeeIndex === -1 ? sections : sections.slice(0, committeeIndex);
  const sectionsAfterCommittee =
    committeeIndex === -1
      ? []
      : sections.slice(
          servedCommitteeIndex === -1 ? committeeIndex : committeeIndex + 1,
        );
  const contacts = account.contacts.map((contact) => ({
    accountId: account.id,
    contactId: contact.id,
    name: contact.name,
    title: contact.title,
    persona: contact.persona,
    emailState: contact.emailVerified
      ? ("verified" as const)
      : ("not_requested" as const),
  }));

  return (
    <div className={`${components.detailBody} ${styles.accountOverviewBody}`}>
      {sectionsBeforeCommittee.length > 0 ? (
        <ResearchOverview
          accountId={account.id}
          contacts={contacts}
          evidence={account.researchEvidence}
          overallFit={account.overallFit}
          sections={sectionsBeforeCommittee}
        />
      ) : null}
      <BuyingCommitteeTable
        accountId={account.id}
        members={account.buyingCommittee}
      />
      {sectionsAfterCommittee.length > 0 ? (
        <ResearchOverview
          accountId={account.id}
          contacts={contacts}
          evidence={account.researchEvidence}
          overallFit={account.overallFit}
          sections={sectionsAfterCommittee}
        />
      ) : null}
      <Link
        className={`${readability.actionMedium} flex h-8 w-fit items-center gap-1 rounded-[var(--clue-ds-product-component-button-sm-radius)] px-2 text-[var(--clue-content-subtle)] hover:bg-[var(--clue-background-hover)] hover:text-[var(--clue-content-neutral)]`}
        href={`/accounts/${account.id}/insights`}
      >
        Open all insights
        <ArrowRight aria-hidden="true" size={13} strokeWidth={1.5} />
      </Link>
    </div>
  );
}
