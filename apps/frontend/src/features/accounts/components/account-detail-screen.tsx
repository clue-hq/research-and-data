import Link from "./research-link";
import motion from "./account-motion.module.css";
import type { AccountDetail, AccountInsight } from "../model/account-detail";
import readability from "./account-readability.module.css";
import components from "./account-components.module.css";
import {
  AccountDetailsList,
  AccountIdentity,
  AccountTextSection,
  FitBadge,
} from "./account-detail-primitives";
import {
  AccountDetailsRail,
  AccountWorkspaceShell,
} from "./account-workspace-shell";
import { ContactAvatar } from "./contact-avatar";
import { AccountResearchOverview } from "./account-research-overview";
import { AccountActivityFeed } from "./account-activity-feed";

function FitCriteria({ account }: { account: AccountDetail }) {
  return (
    <section>
      <div className="flex h-6 items-center gap-2">
        <span className={`${readability.sectionHeading} text-[var(--clue-content-subtle)]`}>
          Overall fit:
        </span>
        <FitBadge compact fit={account.overallFit} />
      </div>
      <div className="mt-4 space-y-6">
        {account.fitCriteria.map((criterion) => (
          <div className={readability.bodyCopy} key={criterion.id}>
            <h3 className="font-medium">{criterion.title}</h3>
            <p className="mt-1 text-[var(--clue-content-subtle)]">
              {criterion.evidence}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}

function InsightSourceIcon({ source }: { source: AccountInsight["source"] }) {
  const path =
    source === "linkedin"
      ? "/logos/linkedin.svg"
      : source === "x"
        ? "/logos/x.svg"
        : "/icons/detail/source.svg";

  return (
    <span className="flex size-4 shrink-0 items-center justify-center">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img alt="" className="max-h-4 max-w-4 object-contain" src={path} />
    </span>
  );
}

function Insights({ account }: { account: AccountDetail }) {
  return (
    <section className="pb-12">
      <div className="flex h-5 items-center justify-between">
        <h2 className={`${readability.sectionHeading} text-[var(--clue-content-subtle)]`}>
          Insights &amp; evidence
        </h2>
        <Link
          className={readability.actionMedium}
          href={`/accounts/${account.id}/insights`}
        >
          See all
        </Link>
      </div>
      <div className="mt-3">
        {account.insights.map((insight) => (
          <a
            className={`${readability.uiRegular} flex h-8 items-center gap-2`}
            href={insight.url}
            key={insight.id}
            rel="noreferrer"
            target="_blank"
          >
            <InsightSourceIcon source={insight.source} />
            <span className={`${readability.uiMedium} min-w-0 flex-1 truncate`}>
              {insight.title}
            </span>
            <time className="w-36 shrink-0 text-right text-[var(--clue-content-subtle)]">
              {insight.dateLabel}
            </time>
          </a>
        ))}
      </div>
    </section>
  );
}

function ContactsPanel({ account }: { account: AccountDetail }) {
  return (
    <section className={components.detailRailSection}>
      <h2 className={readability.sectionHeading}>Contacts</h2>
      <div className="mt-6 space-y-4">
        {account.contacts.slice(0, 3).map((contact) => (
          <Link
            className="flex h-6 items-center gap-2 rounded-md hover:bg-[var(--clue-background-hover)]"
            href={
              contact.hasDetail
                ? `/accounts/${account.id}/contacts/${contact.id}`
                : `/accounts/${account.id}/contacts`
            }
            key={contact.id}
          >
            <ContactAvatar
              name={contact.name}
              size={24}
              src={contact.avatarUrl}
            />
            <span className={readability.uiRegular}>{contact.name}</span>
          </Link>
        ))}
      </div>
      <Link
        className={`${readability.actionMedium} mt-4 inline-block`}
        href={`/accounts/${account.id}/contacts`}
      >
        See all
      </Link>
    </section>
  );
}

function ActivityPanel({ account }: { account: AccountDetail }) {
  return (
    <section className={components.detailRailSection}>
      <h2 className={readability.sectionHeading}>Activity</h2>
      <AccountActivityFeed compact items={account.activity} label="Recent account activity" />
    </section>
  );
}

function DetailsPanel({ account }: { account: AccountDetail }) {
  return (
    <AccountDetailsRail>
      <section className={components.detailRailSection}>
        <h2 className={readability.sectionHeading}>Account details</h2>
        <div className="mt-[22px]">
          <AccountDetailsList account={account} />
        </div>
      </section>
      <ContactsPanel account={account} />
      <ActivityPanel account={account} />
    </AccountDetailsRail>
  );
}

export function AccountDetailScreen({
  account,
}: {
  account: AccountDetail;
}) {
  return (
    <AccountWorkspaceShell account={account} activeTab="overview">
      <div className={components.recordLayout}>
        <section className={`${motion.pageEntry} clue-scrollbar-hidden ${components.recordScroll}`}>
          <article className={components.detailArticle}>
            {account.overviewDisplay ? (
              <AccountResearchOverview account={account} />
            ) : (
              <>
              <AccountIdentity account={account} />
              <div className={components.detailBody}>
                <div>
                  <AccountTextSection
                    paragraphs={account.summaryParagraphs}
                    title="Account summary"
                  />
                </div>
                <div>
                  <AccountTextSection
                    paragraphs={account.businessParagraphs}
                    title="About their business"
                  />
                </div>
                <FitCriteria account={account} />
                <Insights account={account} />
              </div>
              </>
            )}
          </article>
        </section>
        <DetailsPanel account={account} />
      </div>
    </AccountWorkspaceShell>
  );
}
