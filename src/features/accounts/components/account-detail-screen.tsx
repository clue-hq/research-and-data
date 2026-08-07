import Link from "next/link";
import { DesignIcon } from "@/components/ui/design-icon";
import { SidebarIcon } from "@/components/shell/sidebar-icon";
import type { AccountDetail, AccountInsight } from "../model/account-detail";
import readability from "./account-readability.module.css";
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

function FitCriteria({ account }: { account: AccountDetail }) {
  return (
    <section className="mt-9">
      <div className="flex h-6 items-center gap-2">
        <span className={`${readability.fieldLabel} text-[var(--clue-content-subtle)]`}>
          Overall fit:
        </span>
        <FitBadge compact fit={account.overallFit} />
      </div>
      <div className="mt-2">
        {account.fitCriteria.map((criterion) => (
          <div className="flex min-h-[82px] items-start" key={criterion.id}>
            <span className="mt-2 flex size-6 shrink-0 items-center justify-center rounded-full bg-[var(--clue-background-page)]">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                alt=""
                className="max-h-3 max-w-3 object-contain"
                src={
                  criterion.matched
                    ? "/icons/detail/criteria-pass.svg"
                    : "/icons/detail/criteria-fail.svg"
                }
              />
            </span>
            <div className={`${readability.uiRegular} ml-2 mt-2 min-w-0`}>
              <h3>{criterion.title}</h3>
              <p className="text-[var(--clue-content-subtle)]">
                {criterion.evidence}
              </p>
            </div>
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
    <section className="mt-9 pb-12">
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
    <section className="border-b-[0.5px] border-[var(--clue-border-neutral)] px-4 pb-3 pt-[23px]">
      <h2 className={readability.sectionHeading}>Contacts</h2>
      <div className="mt-6 space-y-4">
        {account.contacts.map((contact) => (
          <Link
            className="flex h-6 items-center gap-2 rounded-md hover:bg-[var(--clue-background-hover)]"
            href={
              contact.id === "denise-dresser"
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

function ActivityIcon({
  kind,
}: {
  kind: AccountDetail["activity"][number]["kind"];
}) {
  if (kind === "contacts") {
    return <SidebarIcon name="account" />;
  }
  return (
    <DesignIcon
      name={kind === "summary" ? "artifacts" : "progress-75"}
      size={16}
    />
  );
}

function ActivityPanel({ account }: { account: AccountDetail }) {
  return (
    <section className="border-b-[0.5px] border-[var(--clue-border-neutral)] px-4 pb-4 pt-5">
      <h2 className={readability.sectionHeading}>Activity</h2>
      <div className="mt-4 space-y-4">
        {account.activity.map((item) => (
          <div className="flex h-5 items-center gap-3" key={item.id}>
            <ActivityIcon kind={item.kind} />
            <p className={readability.uiRegular}>
              {item.text}{" "}
              <span className="text-[var(--clue-content-subtle)]">
                {item.timeLabel}
              </span>
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}

function DetailsPanel({ account }: { account: AccountDetail }) {
  return (
    <AccountDetailsRail>
      <section className="border-b-[0.5px] border-[var(--clue-border-neutral)] px-4 pb-[10px] pt-[22px]">
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
      <div className="flex h-full min-h-0 min-w-0">
        <section className="clue-scrollbar-hidden min-w-0 flex-1 overflow-y-auto">
          <article className="mx-auto w-full max-w-[720px] px-8 pt-12">
              <AccountIdentity account={account} />
              <div className="mt-9">
                <AccountTextSection
                  paragraphs={account.summaryParagraphs}
                  title="Account summary"
                />
              </div>
              <div className="mt-9">
                <AccountTextSection
                  paragraphs={account.businessParagraphs}
                  title="About their business"
                />
              </div>
              <FitCriteria account={account} />
              <Insights account={account} />
          </article>
        </section>
        <DetailsPanel account={account} />
      </div>
    </AccountWorkspaceShell>
  );
}
