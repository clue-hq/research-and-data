import Link from "next/link";
import type {
  AccountDetail,
  AccountProjectSection,
} from "../model/account-detail";
import { contactPersonaLabel } from "../model/account-contact";
import { contactProfileLinkAccessibleName } from "../model/contact-accessibility";
import {
  formatFieldKeyLabel,
  formatIsoDate,
  formatScore,
  formatToken,
} from "../model/formatting";
import readability from "./account-readability.module.css";
import {
  AccountCoveragePanel,
  AccountDetailsList,
  AccountIdentity,
  AccountTextSection,
  TokenBadge,
} from "./account-detail-primitives";
import { Absent, FactValue, Provenance } from "./account-facts";
import {
  AccountDetailsRail,
  AccountWorkspaceShell,
} from "./account-workspace-shell";
import { ContactAvatar } from "./contact-avatar";

function sectionTitle(section: AccountProjectSection) {
  if (section.projectId === null) return "Not attributed to a project";
  return section.name ?? "Unnamed project";
}

function sectionSubtitle(section: AccountProjectSection) {
  if (section.projectId === null) {
    return "Claims whose run maps to no project — manual ingestion and the documented lineage exemptions.";
  }
  const addedAt = formatIsoDate(section.addedAt);
  if (section.addedVia && addedAt) {
    return `Added ${formatToken(section.addedVia).toLocaleLowerCase()} · ${addedAt}`;
  }
  if (addedAt) return `Added ${addedAt}`;
  // No membership row: this project produced research without targeting the
  // account. Reported rather than hidden.
  return "This project produced research without a membership record.";
}

/**
 * One project's slice of the research.
 *
 * Scores, value narratives (plural — one per persona) and insights are shown
 * inside the project that produced them: a score from one project is never
 * attributed to another, and the unattributed bucket is labelled as such
 * instead of being folded into a project.
 */
function ProjectSection({ section }: { section: AccountProjectSection }) {
  const empty =
    !section.scores.length &&
    !section.narratives.length &&
    !section.insights.length;

  return (
    <section className="mt-8">
      <div className="flex flex-wrap items-baseline gap-2">
        <h3 className={readability.uiMedium}>{sectionTitle(section)}</h3>
        <span
          className={`${readability.fieldLabel} text-[var(--clue-content-subtle)]`}
        >
          {sectionSubtitle(section)}
        </span>
      </div>

      {empty ? (
        <p
          className={`${readability.uiRegular} mt-2 text-[var(--clue-content-subtle)]`}
        >
          Targeted, nothing produced yet.
        </p>
      ) : null}

      {section.scores.length ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {section.scores.map((score) => (
            <TokenBadge
              compact
              key={`${score.icpKey}-${score.icpVersion}-${score.scoredAt}`}
            >
              Fit {formatScore(score.fit) ?? "—"} · Intent{" "}
              {formatScore(score.intent) ?? "—"}
              {score.icpKey
                ? ` · ICP ${score.icpKey} v${score.icpVersion ?? 1}`
                : ""}
            </TokenBadge>
          ))}
        </div>
      ) : null}

      {section.narratives.length ? (
        <div className="mt-4 space-y-3">
          {section.narratives.map((narrative, index) => (
            <article
              className="rounded-lg border-[0.5px] border-[var(--clue-border-neutral)] p-3"
              key={`${narrative.fieldKey}-${index}`}
            >
              <h4
                className={`${readability.fieldLabel} text-[var(--clue-content-subtle)]`}
                title={narrative.fieldKey}
              >
                {formatFieldKeyLabel(narrative.fieldKey)}
              </h4>
              <div className={`${readability.uiRegular} mt-1.5`}>
                <FactValue value={narrative.value} />
              </div>
              <div className={`${readability.fieldLabel} mt-2`}>
                <Provenance
                  observedAt={narrative.observedAt}
                  provider={narrative.provider}
                />
              </div>
            </article>
          ))}
        </div>
      ) : null}

      {section.insights.length ? (
        <div className="mt-4 space-y-3">
          {section.insights.map((insight, index) => (
            <div
              className={`${readability.uiRegular} flex flex-col gap-1`}
              key={`${insight.fieldKey}-${index}`}
            >
              <span
                className={`${readability.fieldLabel} text-[var(--clue-content-subtle)]`}
                title={insight.fieldKey}
              >
                {formatFieldKeyLabel(insight.fieldKey)}
              </span>
              <FactValue value={insight.value} />
              <span className={readability.fieldLabel}>
                <Provenance
                  observedAt={insight.observedAt}
                  provider={insight.provider}
                />
              </span>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function ProjectSections({ account }: { account: AccountDetail }) {
  return (
    <section className="mt-9 pb-12">
      <h2
        className={`${readability.sectionHeading} text-[var(--clue-content-subtle)]`}
      >
        Research by project
      </h2>
      {account.projectSections.length ? (
        account.projectSections.map((section) => (
          <ProjectSection
            key={section.projectId ?? "unattributed"}
            section={section}
          />
        ))
      ) : (
        <p
          className={`${readability.uiRegular} mt-3 text-[var(--clue-content-subtle)]`}
        >
          No project has produced research on this account yet.
        </p>
      )}
    </section>
  );
}

/**
 * The buying committee.
 *
 * Empty is a legitimate answer today: the governed committee reads M8D
 * research references whose production writer is still quarantined, so the
 * endpoint returns an empty list rather than a 404.
 */
function CommitteePanel({ account }: { account: AccountDetail }) {
  return (
    <section className="border-b-[0.5px] border-[var(--clue-border-neutral)] px-4 pb-3 pt-[23px]">
      <h2 className={readability.sectionHeading}>Buying committee</h2>
      <div className="mt-6 space-y-4">
        {account.committee.length ? (
          account.committee.map((member) => (
            <Link
              aria-label={contactProfileLinkAccessibleName(member.name)}
              className="flex min-h-6 items-center gap-2 rounded-md hover:bg-[var(--clue-background-hover)]"
              href={`/accounts/${account.id}/contacts/${member.contactId}`}
              key={member.contactId}
            >
              <ContactAvatar decorative name={member.name} size={24} />
              <span className={readability.uiRegular}>
                {member.name ?? "Unnamed contact"}
              </span>
              <span
                className={`${readability.fieldLabel} text-[var(--clue-content-subtle)]`}
              >
                {contactPersonaLabel(member.persona)}
              </span>
            </Link>
          ))
        ) : (
          <p className={readability.uiRegular}>
            <Absent label="No committee resolved yet" />
          </p>
        )}
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

function DetailsPanel({ account }: { account: AccountDetail }) {
  return (
    <AccountDetailsRail>
      <section className="border-b-[0.5px] border-[var(--clue-border-neutral)] px-4 pb-[10px] pt-[22px]">
        <h2 className={readability.sectionHeading}>Account details</h2>
        <div className="mt-[22px]">
          <AccountDetailsList account={account} />
        </div>
      </section>
      <CommitteePanel account={account} />
      <section className="border-b-[0.5px] border-[var(--clue-border-neutral)] px-4 pb-4 pt-5">
        <AccountCoveragePanel account={account} />
      </section>
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
                emptyNote="A written account summary is composed once this account's deep research completes."
                title="Account summary"
              />
            </div>
            <ProjectSections account={account} />
          </article>
        </section>
        <DetailsPanel account={account} />
      </div>
    </AccountWorkspaceShell>
  );
}
