"use client";
import motion from "./account-motion.module.css";

import type { AccountDetail } from "../model/account-detail";
import type {
  AccountWorkspace,
  WorkspaceInsight,
} from "../model/account-workspace";
import readability from "./account-readability.module.css";
import { insightHeaderSummary } from "../model/account-workspace-presentation";
import research from "./account-research.module.css";
import { AccountWorkspaceShell } from "./account-workspace-shell";
import { ResearchDocument } from "./research-content";

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
  if (workspace.insightsDisplay) {
    return (
      <AccountWorkspaceShell account={account} activeTab="insights">
        <div className={`${motion.pageEntry} ${research.documentPage} clue-scrollbar-hidden`}>
          <div className={research.insightsCanvas}>
            <header className={research.insightsIntro}>
              <h1 className={research.pageTitle}>Account insights</h1>
              <ul aria-label="Research summary" className={research.summaryStrip}>
                {insightHeaderSummary(workspace.insightSummary).map((item) => (
                  <li className={research.summaryItem} key={item}>
                    {item}
                  </li>
                ))}
              </ul>
            </header>
            <ResearchDocument
              accountId={account.id}
              evidence={workspace.researchEvidence}
              sections={workspace.insightsDisplay.sections}
              summary={workspace.insightSummary}
            />
          </div>
        </div>
      </AccountWorkspaceShell>
    );
  }

  return (
    <AccountWorkspaceShell account={account} activeTab="insights">
      <div className={`${motion.pageEntry} clue-scrollbar-hidden h-full overflow-y-auto`}>
        <article className="mx-auto w-full max-w-[720px] px-8 pt-12 pb-16">
          <h1 className={readability.detailTitle}>Insights</h1>
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
                    {insight.sourceLabel}
                  </p>
                  <p className="mt-1">{insight.summary}</p>
                </div>
              </a>
            ))}
          </div>
        </article>
      </div>
    </AccountWorkspaceShell>
  );
}

export { AccountArtifactsScreen, AccountActivityScreen } from "./account-library-screens";
