import Link from "next/link";
import {
  accountActivityActorLabel,
  accountActivityEventHref,
  accountActivityEventLabel,
  accountActivitySubjectLabel,
  accountActivitySummaryLabel,
  type AccountActivity,
  type AccountActivityKind,
} from "../model/account-activity";
import {
  accountArtifactStateCopy,
  type AccountArtifactState,
} from "../model/account-artifacts";
import type { AccountDetail } from "../model/account-detail";
import type {
  AccountWorkspace,
  WorkspaceInsight,
} from "../model/account-workspace";
import { accountEvidenceArtifactHref } from "../model/evidence";
import { formatIsoDateTime } from "../model/formatting";
import { EvidenceList } from "./evidence-list";
import readability from "./account-readability.module.css";
import { AccountWorkspaceShell } from "./account-workspace-shell";

/** Plain honest absence for workspace-backed reads that returned no records. */
function WorkspaceTabEmptyState({ children }: { children: React.ReactNode }) {
  return (
    <p
      className={`${readability.uiRegular} mt-6 text-[var(--clue-content-subtle)]`}
    >
      {children}
    </p>
  );
}

function InsightIcon({ source }: { source: WorkspaceInsight["source"] }) {
  const path =
    source === "linkedin"
      ? "/logos/linkedin.svg"
      : source === "x"
        ? "/logos/x.svg"
        : "/icons/detail/link.svg";
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img alt="" aria-hidden="true" className="mt-0.5 size-4 object-contain" src={path} />
  );
}

export function AccountInsightsScreen({
  account,
  workspace,
}: {
  account: AccountDetail;
  workspace: AccountWorkspace;
}) {
  const liveEvidence = [
    ...account.neutralFacts.map((fact) => fact.evidence),
    ...account.projectSections.flatMap((section) =>
      section.insights.map((fact) => fact.evidence),
    ),
  ];
  return (
    <AccountWorkspaceShell account={account} activeTab="insights">
      <div className="clue-scrollbar-hidden h-full overflow-y-auto">
        <article className="mx-auto w-full max-w-[720px] px-8 pt-12 pb-16">
          <h1 className={readability.detailTitle}>Insights</h1>
          {workspace.insights.length || liveEvidence.length ? null : (
            <WorkspaceTabEmptyState>
              No inspectable account evidence is served yet.
            </WorkspaceTabEmptyState>
          )}
          <div className="mt-6 space-y-7">
            {workspace.insights.map((insight) => (
              <a
                className="grid grid-cols-[16px_minmax(0,1fr)] gap-2"
                href={insight.url}
                key={insight.id}
                rel="noreferrer"
                target="_blank"
              >
                <InsightIcon source={insight.source} />
                <div className={`${readability.uiRegular} min-w-0`}>
                  <h2 className={readability.uiMedium}>{insight.title}</h2>
                  <p className="truncate text-[var(--clue-content-subtle)] underline underline-offset-2">
                    {insight.url}
                  </p>
                  <p className="mt-1">{insight.summary}</p>
                </div>
              </a>
            ))}
          </div>
          {liveEvidence.length ? (
            <section className="mt-8">
              <h2 className={readability.sectionHeading}>Research evidence</h2>
              <div className="mt-4">
                <EvidenceList
                  artifactHref={(evidence) =>
                    accountEvidenceArtifactHref(account.id, evidence.claimId)
                  }
                  evidence={liveEvidence}
                />
              </div>
            </section>
          ) : null}
        </article>
      </div>
    </AccountWorkspaceShell>
  );
}

export function AccountArtifactsScreen({
  account,
  state,
}: {
  account: AccountDetail;
  state: AccountArtifactState;
}) {
  const copy = accountArtifactStateCopy(state);

  return (
    <AccountWorkspaceShell account={account} activeTab="artifacts">
      <div className="clue-scrollbar-hidden h-full overflow-y-auto">
        <section className="mx-auto w-full max-w-[720px] px-8 pt-12 pb-16">
          <h1 className={readability.detailTitle}>Artifacts</h1>
          <section
            aria-labelledby="account-artifact-state-title"
            className="mt-7 max-w-xl rounded-xl border border-[var(--clue-border-neutral)] bg-[var(--clue-background-page)] p-5"
          >
            <h2
              className={readability.sectionHeading}
              id="account-artifact-state-title"
            >
              {copy.title}
            </h2>
            <p
              className={`${readability.uiRegular} mt-2 text-[var(--clue-content-subtle)]`}
            >
              {copy.description}
            </p>
          </section>
        </section>
      </div>
    </AccountWorkspaceShell>
  );
}

function ActivityMark({
  kind,
}: {
  kind: AccountActivityKind;
}) {
  const path =
    kind === "research_view.recheck_completed"
      ? "/icons/check.svg"
      : kind === "research_view.section_stale"
        ? "/icons/progress-75.svg"
        : "/icons/research.svg";
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img alt="" aria-hidden="true" className="size-4 object-contain" src={path} />
  );
}

export function AccountActivityScreen({
  account,
  activity,
}: {
  account: AccountDetail;
  activity: AccountActivity;
}) {
  return (
    <AccountWorkspaceShell account={account} activeTab="activity">
      <div className="clue-scrollbar-hidden h-full overflow-y-auto">
        <section className="mx-auto w-full max-w-[720px] px-8 pt-12">
          <h1 className={readability.detailTitle}>Activity</h1>
          <p
            className={`${readability.uiRegular} mt-3 text-[var(--clue-content-subtle)]`}
          >
            Current state: {" "}
            <Link
              className="text-[var(--clue-content-default)] underline decoration-[var(--clue-border-neutral)] underline-offset-2"
              href={`/accounts/${account.id}/contacts`}
            >
              {activity.state.committeeCount}{" "}
              {activity.state.committeeCount === 1 ? "contact" : "contacts"}
            </Link>
            {" · "}
            <Link
              className="text-[var(--clue-content-default)] underline decoration-[var(--clue-border-neutral)] underline-offset-2"
              href={`/accounts/${account.id}`}
            >
              {accountActivitySummaryLabel(activity.state.summary)}
            </Link>
          </p>
          {activity.events.length ? null : (
            <WorkspaceTabEmptyState>
              No durable activity exists for this account yet.
            </WorkspaceTabEmptyState>
          )}
          <div className="relative mt-7 space-y-5 before:absolute before:top-2 before:bottom-2 before:left-[7.5px] before:w-px before:bg-[var(--clue-border-neutral)]">
            {activity.events.map((item) => {
              const timestamp = formatIsoDateTime(item.occurredAt);
              return (
                <div
                  className={`${readability.uiRegular} relative z-10 grid grid-cols-[16px_minmax(0,1fr)] items-start gap-3 bg-white`}
                  key={item.id}
                >
                  <ActivityMark kind={item.kind} />
                  <div>
                    <Link
                      className="font-medium text-[var(--clue-content-default)] hover:underline"
                      href={accountActivityEventHref(account.id, item)}
                    >
                      {accountActivityEventLabel(item.kind)}
                    </Link>
                    <p className="mt-0.5 text-[var(--clue-content-subtle)]">
                      {accountActivityActorLabel(item.actorCategory)}
                      {item.subject.type === "contact" ? (
                        <>
                          {" · "}
                          <Link
                            className="hover:text-[var(--clue-content-default)] hover:underline"
                            href={accountActivityEventHref(account.id, item)}
                          >
                            {accountActivitySubjectLabel(item)}
                          </Link>
                        </>
                      ) : null}
                      {" · "}
                      <Link
                        className="hover:text-[var(--clue-content-default)] hover:underline"
                        href={`/projects/${encodeURIComponent(item.project.id)}`}
                      >
                        {item.project.name}
                      </Link>
                      {timestamp ? (
                        <>
                          {" · "}
                          <time dateTime={item.occurredAt}>{timestamp}</time>
                        </>
                      ) : null}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      </div>
    </AccountWorkspaceShell>
  );
}
