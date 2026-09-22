"use client";

import Image from "next/image";
import Link from "./research-link";
import {
  createContext,
  useContext, useEffect,
} from "react";
import {
  useAccountDetailsPanelController,
  useAccountWorkspaceHeaderController,
} from "../hooks/use-account-workspace-controller";
import type { AccountDetail } from "../model/account-detail";
import { formatAccountDate } from "../model/account-workspace-presentation";
import { AccountFlowIcon } from "./account-flow-icon";
import components from "./account-components.module.css";
import readability from "./account-readability.module.css";
import motion from "./account-motion.module.css";

/** The account glyph shown when the account has no logo asset (ruling S2). */
const ACCOUNT_GLYPH_PATH = "/icons/building.svg";

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
  return <AccountFlowIcon active={active} name={tab} size={12} />;
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
  detailsPreference: boolean | "auto";
  setDetailsVisible: (visible: boolean) => void;
};

const WorkspacePanelContext =
  createContext<WorkspacePanelContextValue | null>(null);

export function AccountPanelsProvider({ children }: { children: React.ReactNode }) {
  const panel = useAccountDetailsPanelController();
  return <WorkspacePanelContext.Provider value={panel}>{children}</WorkspacePanelContext.Provider>;
}

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
  copyLinkLabel,
  lastModifiedAt = account.lastModifiedAt,
  showDetailsToggle,
}: {
  account: AccountDetail;
  activeTab: AccountWorkspaceTab;
  copyLinkLabel: string;
  /**
   * The stamp the "Updated" chip prints. A contact page passes the CONTACT's own
   * `lastModifiedAt` (ruling R8); it used to show the account's, which said the
   * person was updated whenever anything on the account was.
   */
  lastModifiedAt?: string;
  showDetailsToggle: boolean;
}) {
  const panel = useContext(WorkspacePanelContext);
  const controller = useAccountWorkspaceHeaderController(copyLinkLabel);

  return (
    <header className={`${readability.uiRegular} relative z-20 flex h-[var(--clue-ds-product-dimension-header-action-bar-height)] shrink-0 items-center gap-3 border-b-[0.5px] border-l-[0.5px] border-[var(--clue-border-neutral)] bg-[var(--clue-background-neutral)] pr-5 pl-14 lg:px-6`}>
      <div className="flex min-w-0 flex-1 items-center gap-2 overflow-hidden">
        <div className="hidden shrink-0 items-center gap-1 py-0.5 lg:flex">
          <Link
            className={`${readability.uiMedium} flex items-center rounded px-2 py-1 text-[var(--clue-content-subtle)] hover:bg-[var(--clue-background-hover)]`}
            href="/accounts"
            prefetch={false}
            scroll={false}
          >
            Accounts
          </Link>
          <span className="flex size-3 items-center justify-center p-0.5">
            <BreadcrumbSlash />
          </span>
          <Link
            className={`${readability.uiMedium} flex items-center gap-1 rounded px-2 py-1 hover:bg-[var(--clue-background-hover)]`}
            href={`/accounts/${account.id}`}
            prefetch
            scroll={false}
          >
            <Image
              alt=""
              aria-hidden="true"
              className="size-3"
              height={12}
              src={account.logoPath ?? ACCOUNT_GLYPH_PATH}
              unoptimized={account.logoPath != null}
              width={12}
            />
            {account.name}
          </Link>
        </div>

        <nav
          aria-label="Account sections"
          className="clue-scrollbar-hidden flex min-w-0 items-center gap-px overflow-x-auto"
        >
          {tabs.map((tab) => {
            const active = tab.id === activeTab;
            return (
              <Link
                aria-current={active ? "page" : undefined}
                className={`${readability.uiMedium} ${components.workspaceTab} ${
                  active
                    ? components.workspaceTabActive
                    : ""
                }`}
                href={accountTabHref(account.id, tab.id)}
                key={tab.id}
                prefetch
                scroll={false}
              >
                <span className={components.workspaceTabContent}>
                  <AccountTabIcon active={active} tab={tab.id} />
                  <span>{tab.label}</span>
                </span>
              </Link>
            );
          })}
        </nav>
      </div>

      <div className="flex shrink-0 items-center gap-3">
        <time
          className={`${readability.uiRegular} hidden whitespace-nowrap text-[var(--clue-content-subtle)] xl:block`}
          dateTime={lastModifiedAt}
          title={`Last updated ${formatAccountDate(lastModifiedAt)}`}
        >
          Updated {formatAccountDate(lastModifiedAt)}
        </time>
        <button
          aria-label={controller.copy.label}
          className={`${components.iconButton} ${components.headerLinkButton}`}
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
            className={`${components.iconButton} ${components.headerMenuButton}`}
            onClick={controller.toggleMenu}
            type="button"
          >
            <HeaderIcon name="ellipsis" />
          </button>
          {controller.menuOpen ? (
            <div className={`${components.popover} absolute top-9 right-0 w-44 p-1`}>
              {account.websiteUrl ? (
                <Link
                  className={components.menuRow}
                  href={account.websiteUrl}
                  target="_blank"
                >
                  Open company website
                </Link>
              ) : null}
              <button
                className={`${components.menuRow} w-full`}
                onClick={controller.closeMenu}
                type="button"
              >
                Export account
              </button>
            </div>
          ) : null}
        </div>
        {showDetailsToggle && (activeTab === "overview" || activeTab === "contacts") ? <button
          aria-label={
            panel?.detailsVisible ? "Hide details panel" : "Show details panel"
          }
          className={`${components.iconButton} ${components.headerPanelButton}`}
          onClick={() =>
            panel?.setDetailsVisible(!panel.detailsVisible)
          }
          type="button"
        >
          <HeaderIcon name="panel-right-close" />
        </button> : null}
      </div>
    </header>
  );
}

export function AccountWorkspaceShell({
  account,
  activeTab,
  children,
  copyLinkLabel = "Copy account link",
  lastModifiedAt,
  showDetailsToggle = true,
}: {
  account: AccountDetail;
  activeTab: AccountWorkspaceTab;
  children: React.ReactNode;
  copyLinkLabel?: string;
  lastModifiedAt?: string;
  showDetailsToggle?: boolean;
}) {
  return (
        <main className={`${components.recordSurface} flex h-full min-h-0 min-w-0 flex-col overflow-hidden`}>
          <AccountWorkspaceHeader
            account={account}
            activeTab={activeTab}
            copyLinkLabel={copyLinkLabel}
            lastModifiedAt={lastModifiedAt}
            showDetailsToggle={showDetailsToggle}
          />
          <div className={`${motion.workspaceBody} relative min-h-0 min-w-0 flex-1 overflow-hidden`}>
            {children}
          </div>
        </main>
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

  return (
    <RecordDetailsRail
      className={className}
      onClose={() => panel?.setDetailsVisible(false)}
      visible={panel?.detailsPreference ?? "auto"}
    >
      {children}
    </RecordDetailsRail>
  );
}

export function RecordDetailsRail({
  children,
  className = "",
  onClose,
  visible,
}: {
  children: React.ReactNode;
  className?: string;
  onClose: () => void;
  visible: boolean | "auto";
}) {
  useEffect(() => {
    if (visible === false) return;
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && window.matchMedia("(max-width: 1023px)").matches) onClose();
    };
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, [visible, onClose]);

  return (
    <>
      <button
        aria-label="Close details panel"
        className={motion.railBackdrop}
        data-visible={visible}
        inert={visible === false}
        onClick={onClose}
        type="button"
      />
      <div className={motion.railSlot} data-visible={visible} inert={visible === false}>
      <aside
        className={`${components.detailRail} ${motion.railContent} h-full overscroll-contain overflow-y-auto border-l border-[var(--clue-border-neutral)] ${className}`}
      >
        {children}
      </aside>
      </div>
    </>
  );
}
