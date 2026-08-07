"use client";

import Image from "next/image";
import Link from "next/link";
import {
  createContext,
  useContext,
} from "react";
import { ApplicationShell } from "@/components/shell/application-shell";
import {
  useAccountDetailsPanelController,
  useAccountWorkspaceHeaderController,
} from "../hooks/use-account-workspace-controller";
import type { AccountDetail } from "../model/account-detail";
import { AccountFlowIcon } from "./account-flow-icon";
import readability from "./account-readability.module.css";

export type AccountWorkspaceTab =
  | "overview"
  | "contacts"
  | "insights"
  | "artifacts"
  | "activity";

const tabs: Array<{
  id: AccountWorkspaceTab;
  label: string;
}> = [
  { id: "overview", label: "Overview" },
  { id: "contacts", label: "Contacts" },
  { id: "insights", label: "Insights" },
  { id: "artifacts", label: "Artifacts" },
  { id: "activity", label: "Activity" },
];

function AccountTabIcon({
  active,
  tab,
}: {
  active: boolean;
  tab: AccountWorkspaceTab;
}) {
  return <AccountFlowIcon active={active} name={tab} size={16} />;
}

function BreadcrumbSlash() {
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      alt=""
      aria-hidden="true"
      className="size-2 shrink-0"
      src="/icons/detail/breadcrumb-slash.svg?v=account-flow-20260730"
    />
  );
}

type WorkspacePanelContextValue = {
  detailsVisible: boolean;
  setDetailsVisible: (visible: boolean) => void;
};

const WorkspacePanelContext =
  createContext<WorkspacePanelContextValue | null>(null);

function accountTabHref(accountId: string, tab: AccountWorkspaceTab) {
  return tab === "overview"
    ? `/accounts/${accountId}`
    : `/accounts/${accountId}/${tab}`;
}

function HeaderIcon({
  name,
}: {
  name: "ellipsis" | "link" | "panel-right-close";
}) {
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      alt=""
      aria-hidden="true"
      className={
        name === "ellipsis"
          ? "h-[2.167px] w-[10.333px]"
          : name === "panel-right-close"
            ? "size-[13px]"
            : "h-[12.589px] w-[12.601px]"
      }
      src={`/icons/detail/${name}.svg`}
    />
  );
}

function AccountWorkspaceHeader({
  account,
  activeTab,
}: {
  account: AccountDetail;
  activeTab: AccountWorkspaceTab;
}) {
  const panel = useContext(WorkspacePanelContext);
  const controller = useAccountWorkspaceHeaderController();

  return (
    <header className={`${readability.uiRegular} relative z-20 flex h-[var(--clue-ds-product-dimension-header-action-bar-height)] shrink-0 items-center border-b-[0.5px] border-[var(--clue-border-neutral)] bg-white pr-5 pl-14 lg:px-6`}>
      <div className="flex min-w-0 flex-1 items-center overflow-hidden">
        <div className="hidden shrink-0 items-center gap-1 py-0.5 lg:flex">
          <Link
            className="flex items-center rounded px-2 py-1 text-[var(--clue-content-subtle)] hover:bg-[var(--clue-background-hover)]"
            href="/accounts"
            prefetch={false}
            scroll={false}
          >
            Accounts
          </Link>
          <span className="flex size-3 items-center justify-center p-0.5">
            <BreadcrumbSlash />
          </span>
          <span className={`${readability.uiMedium} flex items-center gap-1 rounded px-2 py-1`}>
            <Image
              alt=""
              aria-hidden="true"
              className="size-3"
              height={12}
              src={account.logoPath}
              width={12}
            />
            {account.name}
          </span>
        </div>

        <nav
          aria-label="Account sections"
          className="clue-scrollbar-hidden flex min-w-0 items-center gap-1 overflow-x-auto lg:ml-3"
        >
          {tabs.map((tab) => {
            const active = tab.id === activeTab;
            return (
              <Link
                aria-current={active ? "page" : undefined}
                className={`${readability.uiMedium} flex h-9 shrink-0 items-center gap-2 rounded-[18px] border-[0.5px] px-4 transition-colors ${
                  active
                    ? "border-[var(--clue-border-neutral)] bg-[var(--clue-background-pressed)] text-[var(--clue-content-neutral)]"
                    : "border-transparent text-[var(--clue-content-subtle)] opacity-80 hover:bg-[var(--clue-background-hover)] hover:opacity-100"
                }`}
                href={accountTabHref(account.id, tab.id)}
                key={tab.id}
                prefetch
                scroll={false}
              >
                <AccountTabIcon active={active} tab={tab.id} />
                <span>{tab.label}</span>
              </Link>
            );
          })}
        </nav>
      </div>

      <div className="ml-4 flex shrink-0 items-center gap-2.5">
        <button
          aria-label={controller.copy.label}
          className="flex size-5 items-center justify-center rounded-md hover:bg-[var(--clue-background-hover)]"
          onClick={controller.copy.copyCurrentUrl}
          title={controller.copy.label}
          type="button"
        >
          <HeaderIcon name="link" />
        </button>
        <div className="relative">
          <button
            aria-expanded={controller.menuOpen}
            aria-label="More account actions"
            className="flex size-6 items-center justify-center rounded-md hover:bg-[var(--clue-background-hover)]"
            onClick={controller.toggleMenu}
            type="button"
          >
            <HeaderIcon name="ellipsis" />
          </button>
          {controller.menuOpen ? (
            <div className="absolute top-9 right-0 w-44 rounded-lg border-[0.5px] border-[var(--clue-border-neutral)] bg-white p-1 shadow-[0_10px_30px_rgba(0,24,62,0.12)]">
              <Link
                className="flex h-8 items-center rounded-md px-3 hover:bg-[var(--clue-background-hover)]"
                href={account.websiteUrl}
                target="_blank"
              >
                Open company website
              </Link>
              <button
                className="flex h-8 w-full items-center rounded-md px-3 hover:bg-[var(--clue-background-hover)]"
                onClick={controller.closeMenu}
                type="button"
              >
                Export account
              </button>
            </div>
          ) : null}
        </div>
        <button
          aria-label={
            panel?.detailsVisible ? "Hide details panel" : "Show details panel"
          }
          className="flex size-5 items-center justify-center rounded-lg hover:bg-[var(--clue-background-hover)]"
          onClick={() =>
            panel?.setDetailsVisible(!panel.detailsVisible)
          }
          type="button"
        >
          <HeaderIcon name="panel-right-close" />
        </button>
      </div>
    </header>
  );
}

export function AccountWorkspaceShell({
  account,
  activeTab,
  children,
}: {
  account: AccountDetail;
  activeTab: AccountWorkspaceTab;
  children: React.ReactNode;
}) {
  const panelValue = useAccountDetailsPanelController();

  return (
    <ApplicationShell activeHref="/accounts">
      <WorkspacePanelContext.Provider value={panelValue}>
        <main className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden">
          <AccountWorkspaceHeader account={account} activeTab={activeTab} />
          <div className="clue-view-enter relative min-h-0 min-w-0 flex-1 overflow-hidden">
            {children}
          </div>
        </main>
      </WorkspacePanelContext.Provider>
    </ApplicationShell>
  );
}

export function AccountDetailsRail({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  const panel = useContext(WorkspacePanelContext);
  if (!panel?.detailsVisible) return null;

  return (
    <>
      <button
        aria-label="Close details panel"
        className="absolute inset-0 z-20 bg-[#111827]/10 lg:hidden"
        onClick={() => panel.setDetailsVisible(false)}
        type="button"
      />
      <aside
        className={`clue-panel-enter absolute inset-y-0 right-0 z-30 w-[min(410px,calc(100vw-32px))] shrink-0 overscroll-contain overflow-y-auto border-l-[0.5px] border-[var(--clue-border-neutral)] bg-white shadow-[-8px_0_24px_rgba(0,24,62,0.08)] lg:static lg:z-auto lg:w-[clamp(360px,38.06%,548px)] lg:shadow-none ${className}`}
      >
        {children}
      </aside>
    </>
  );
}
