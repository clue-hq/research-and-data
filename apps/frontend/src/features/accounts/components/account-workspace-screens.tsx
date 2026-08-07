"use client";

import Image from "next/image";
import { useAccountArtifactsController } from "../hooks/use-account-artifacts-controller";
import type { AccountDetail } from "../model/account-detail";
import type {
  AccountArtifact,
  AccountWorkspace,
  WorkspaceInsight,
} from "../model/account-workspace";
import readability from "./account-readability.module.css";
import { AccountWorkspaceShell } from "./account-workspace-shell";

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
  return (
    <AccountWorkspaceShell account={account} activeTab="insights">
      <div className="clue-scrollbar-hidden h-full overflow-y-auto">
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

const artifactIconBackground = {
  document: "bg-[#e9efff] text-[#1f56d8]",
  presentation: "bg-[#ffe3df] text-[#e32218]",
  web: "bg-[#eee6ff] text-[#6b35e8]",
} as const;

function ArtifactCard({
  artifact,
  onOpen,
}: {
  artifact: AccountArtifact;
  onOpen: () => void;
}) {
  return (
    <button
      className="group min-w-0 text-left"
      onClick={onOpen}
      type="button"
    >
      <div className="relative aspect-[202/136] overflow-hidden rounded-lg bg-[var(--clue-background-page)]">
        <Image
          alt=""
          className="object-cover transition-transform duration-200 group-hover:scale-[1.015]"
          fill
          sizes="220px"
          src={artifact.thumbnailPath}
        />
        <span className="absolute right-2 bottom-2 flex size-9 items-center justify-center rounded-lg border-[0.5px] border-[var(--clue-border-neutral)] bg-white shadow-[var(--clue-shadow-low)]">
          <Image
            alt=""
            height={18}
            src="/logos/openai-detail.svg"
            width={18}
          />
        </span>
      </div>
      <div className="mt-3 flex items-center gap-2">
        <span className={`flex size-6 items-center justify-center rounded-md text-[11px] font-medium ${artifactIconBackground[artifact.type]}`}>
          {artifact.type === "presentation"
            ? "P"
            : artifact.type === "document"
              ? "D"
              : "W"}
        </span>
        <span className={`${readability.uiMedium} truncate`}>
          {artifact.title}
        </span>
      </div>
      <p className={`${readability.fieldLabel} mt-1 pl-8 text-[var(--clue-content-subtle)]`}>
        {artifact.lastEditedLabel}
      </p>
    </button>
  );
}

export function AccountArtifactsScreen({
  account,
  workspace,
}: {
  account: AccountDetail;
  workspace: AccountWorkspace;
}) {
  const controller = useAccountArtifactsController(workspace.artifacts);

  return (
    <AccountWorkspaceShell account={account} activeTab="artifacts">
      <div className="clue-scrollbar-hidden h-full overflow-y-auto">
        <section className="mx-auto w-full max-w-[720px] px-8 pt-12 pb-16">
          <h1 className={readability.detailTitle}>Artifacts</h1>
          <div className="mt-7 flex items-center justify-between gap-4">
            <label className="flex h-8 w-60 items-center gap-2 rounded-lg border-[0.5px] border-[var(--clue-border-input)] bg-[var(--clue-background-hover)] px-2 shadow-[var(--clue-shadow-low)]">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img alt="" className="size-3" src="/icons/search.svg" />
              <span className="sr-only">Search artifacts</span>
              <input
                className={`${readability.uiRegular} min-w-0 flex-1 bg-transparent outline-none`}
                onChange={(event) => controller.setSearch(event.target.value)}
                placeholder="Search"
                value={controller.search}
              />
            </label>
            <div className="flex items-center gap-5">
              <button className={readability.actionMedium} type="button">
                Last viewed⌄
              </button>
              <div className="flex h-8 items-center rounded-lg bg-[var(--clue-background-page)] p-0.5">
                <button className="flex size-7 items-center justify-center rounded-md border-[0.5px] border-[var(--clue-border-neutral)] bg-white" type="button">
                  ⊞
                </button>
                <button className="flex size-7 items-center justify-center text-[var(--clue-content-subtle)]" type="button">
                  ≡
                </button>
              </div>
            </div>
          </div>
          <div className="mt-7 grid grid-cols-1 gap-x-7 gap-y-9 sm:grid-cols-2 md:grid-cols-3">
            {controller.visibleArtifacts.map((artifact) => (
              <ArtifactCard
                artifact={artifact}
                key={artifact.id}
                onOpen={() => controller.openArtifact(artifact)}
              />
            ))}
          </div>
        </section>
      </div>

      {controller.selectedArtifact ? (
        <div
          aria-label={`${controller.selectedArtifact.title} preview`}
          aria-modal="true"
          className="fixed inset-0 z-[60] flex items-center justify-center bg-black/20 p-6"
          role="dialog"
        >
          <button
            aria-label="Close artifact preview"
            className="absolute top-6 right-6 z-10 flex size-11 items-center justify-center rounded-full bg-black/30 text-[28px] font-light text-white"
            onClick={controller.closeArtifact}
            type="button"
          >
            ×
          </button>
          <div className="clue-view-enter relative h-[min(720px,80vh)] w-[min(1080px,82vw)] overflow-hidden rounded-lg bg-white shadow-[0_24px_80px_rgba(0,0,0,0.18)]">
            <Image
              alt={`${controller.selectedArtifact.title} preview`}
              className="object-contain"
              fill
              sizes="82vw"
              src={controller.selectedArtifact.thumbnailPath}
            />
          </div>
        </div>
      ) : null}
    </AccountWorkspaceShell>
  );
}

function ActivityMark({
  kind,
}: {
  kind: AccountWorkspace["activity"][number]["kind"];
}) {
  const path =
    kind === "contacts"
      ? "/icons/detail/contacts.png"
      : kind === "summary"
        ? "/icons/artifacts.svg"
        : "/icons/progress-75.svg";
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img alt="" aria-hidden="true" className="size-4 object-contain" src={path} />
  );
}

export function AccountActivityScreen({
  account,
  workspace,
}: {
  account: AccountDetail;
  workspace: AccountWorkspace;
}) {
  return (
    <AccountWorkspaceShell account={account} activeTab="activity">
      <div className="clue-scrollbar-hidden h-full overflow-y-auto">
        <section className="mx-auto w-full max-w-[720px] px-8 pt-12">
          <h1 className={readability.detailTitle}>Activity</h1>
          <div className="relative mt-7 space-y-5 before:absolute before:top-2 before:bottom-2 before:left-[7.5px] before:w-px before:bg-[var(--clue-border-neutral)]">
            {workspace.activity.map((item) => (
              <div
                className={`${readability.uiRegular} relative z-10 flex items-center gap-3 bg-white`}
                key={item.id}
              >
                <ActivityMark kind={item.kind} />
                <p>
                  {item.text}{" "}
                  <span className="text-[var(--clue-content-subtle)]">
                    {item.timeLabel}
                  </span>
                </p>
              </div>
            ))}
          </div>
        </section>
      </div>
    </AccountWorkspaceShell>
  );
}
