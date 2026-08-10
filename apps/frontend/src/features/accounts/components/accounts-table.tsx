"use client";

import Link from "next/link";
import { DesignIcon } from "@/components/ui/design-icon";
import type { Account } from "../model/account";
import {
  formatEmployeeCount,
  formatResearchStatus,
  formatRevenueBand,
  formatScore,
} from "../model/formatting";
import {
  accountColumnWidthConstraints,
  defaultAccountColumnWidths,
  defaultAccountColumns,
  getFirstScrollableAccountColumn,
  type AccountColumnKey,
  type AccountColumnWidths,
  type AccountTableDensity,
} from "../model/account-table-view";
import readability from "./account-readability.module.css";
import { AccountAvatar } from "./account-avatar";
import { AccountCheckbox } from "./account-checkbox";
import { Absent } from "./account-facts";
import { ColumnResizeHandle } from "./column-resize-handle";

const densityHeightClasses: Record<AccountTableDensity, string> = {
  compact: "h-[var(--clue-ds-product-dimension-table-row-compact)]",
  comfortable: "h-[var(--clue-ds-product-dimension-table-row-comfortable)]",
  spacious: "h-[var(--clue-ds-product-dimension-table-row-spacious)]",
};

function accountGridTemplate(
  visibleColumns: Record<AccountColumnKey, boolean>,
  columnOrder: AccountColumnKey[],
  columnWidths: AccountColumnWidths,
) {
  const orderedVisibleColumns = columnOrder.filter(
    (column) => visibleColumns[column],
  );

  return ["56px"]
    .concat(
      orderedVisibleColumns.map((column, index) =>
        index === orderedVisibleColumns.length - 1
          ? `minmax(${columnWidths[column]}px, 1fr)`
          : `${columnWidths[column]}px`,
      ),
    )
    .join(" ");
}

function accountTableMinWidth(
  visibleColumns: Record<AccountColumnKey, boolean>,
  columnWidths: AccountColumnWidths,
) {
  return (
    56 +
    (Object.keys(columnWidths) as AccountColumnKey[]).reduce(
      (total, column) =>
        total +
        (visibleColumns[column] ? columnWidths[column] : 0),
      0,
    )
  );
}

const leadingCellBorder =
  "border-b-[0.5px] border-[var(--clue-border-table)]";
const cellBorder =
  "border-l-[0.5px] border-b-[0.5px] border-[var(--clue-border-table)]";
const pinnedCellBorder =
  "border-x-[0.5px] border-b-[0.5px] border-[var(--clue-border-table)]";
const leadingHeaderBorder =
  "border-t-[0.5px] border-b-[0.5px] border-[var(--clue-border-table)]";
const headerBorder =
  "border-t-[0.5px] border-l-[0.5px] border-b-[0.5px] border-[var(--clue-border-table)]";
const pinnedHeaderBorder =
  "border-[0.5px] border-[var(--clue-border-table)]";

const columnLabels: Record<AccountColumnKey, { icon: string; label: string }> = {
  company: { icon: "building", label: "Company name" },
  research: { icon: "research", label: "Research status" },
  score: { icon: "hash", label: "Fit score" },
  revenue: { icon: "hash", label: "Revenue" },
  size: { icon: "circle-chevron-down", label: "Employees" },
  projects: { icon: "circle-chevron-down", label: "Projects" },
};

function HeaderCell({
  column,
  onResize,
  onReset,
  order,
  showLeadingDivider = true,
  pinned = false,
  width,
}: {
  column: AccountColumnKey;
  onResize: (column: AccountColumnKey, width: number) => void;
  onReset: (column: AccountColumnKey) => void;
  order: number;
  showLeadingDivider?: boolean;
  pinned?: boolean;
  width: number;
}) {
  const constraints = accountColumnWidthConstraints[column];
  const { icon, label } = columnLabels[column];

  return (
    <div
      className={`${readability.uiMedium} relative flex h-[var(--clue-ds-product-dimension-table-header-height)] items-center gap-1 px-4 ${
        pinned
          ? pinnedHeaderBorder
          : showLeadingDivider
            ? headerBorder
            : leadingHeaderBorder
      } ${
        pinned
          ? "sticky left-14 z-30 overflow-hidden bg-white"
          : ""
      }`}
      role="columnheader"
      style={{ order }}
    >
      <DesignIcon name={icon} size={12} />
      <span className="whitespace-nowrap text-[var(--clue-content-neutral)]">
        {label}
      </span>
      <ColumnResizeHandle
        label={label}
        max={constraints.max}
        min={constraints.min}
        onChange={(nextWidth) => onResize(column, nextWidth)}
        onReset={() => onReset(column)}
        width={width}
      />
    </div>
  );
}

/**
 * Research status is a per-project fact, so a global-lens row can legitimately
 * carry several. Distinct statuses render as chips, each naming the projects it
 * came from; an account no project has researched renders an honest absence
 * rather than an invented "Not started".
 */
function ResearchStatusCell({ account }: { account: Account }) {
  if (!account.researchStatus.length) return <Absent label="Not researched" />;

  const byStatus = new Map<string, string[]>();
  for (const entry of account.researchStatus) {
    const membership = account.projects.find(
      (project) => project.projectId === entry.projectId,
    );
    // A status entry can name a project this account has no membership row
    // for — research was launched for a project that no longer targets it. The
    // wire reports that rather than hiding it, so the tooltip says exactly
    // that instead of implying the status covers every project.
    const label = membership
      ? membership.name ?? "Unnamed project"
      : "A project that no longer targets this account";
    byStatus.set(entry.status, [...(byStatus.get(entry.status) ?? []), label]);
  }

  return (
    <span className="flex min-w-0 items-center gap-1.5 overflow-hidden">
      {[...byStatus.entries()].map(([status, projectNames]) => (
        <span
          className={`${readability.pillMedium} flex h-6 w-fit shrink-0 items-center gap-2 rounded-xl bg-[var(--clue-background-pressed)] px-2 shadow-[var(--clue-shadow-low)]`}
          key={status}
          title={projectNames.join(", ")}
        >
          {status === "in_progress" ? (
            <DesignIcon name="spinner" size={12} />
          ) : null}
          <span className="whitespace-nowrap">
            {formatResearchStatus(
              status as Account["researchStatus"][number]["status"],
            )}
          </span>
        </span>
      ))}
    </span>
  );
}

/**
 * A row can hold several scores — one project can score an account under
 * several ICPs and versions, and no representative run is chosen. Each score
 * is shown with the ICP behind it rather than collapsed into one number.
 */
function FitScoreCell({ account }: { account: Account }) {
  const scored = account.scores.filter((score) => score.fit !== null);
  if (!scored.length) return <Absent label="Not scored" />;

  return (
    <span className="flex min-w-0 items-center gap-2 overflow-hidden">
      {scored.map((score) => {
        const projectName =
          account.projects.find(
            (project) => project.projectId === score.projectId,
          )?.name ?? null;
        return (
          <span
            className="flex shrink-0 items-center gap-1"
            key={`${score.projectId}-${score.icpKey}-${score.icpVersion}`}
            title={[
              projectName,
              score.icpKey
                ? `ICP ${score.icpKey} v${score.icpVersion ?? 1}`
                : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          >
            <DesignIcon name="progress-75" size={13} />
            <span>{formatScore(score.fit)}</span>
          </span>
        );
      })}
    </span>
  );
}

/** Never renders a project id: an unnamed project is shown as unnamed. */
function ProjectsCell({ account }: { account: Account }) {
  if (!account.projects.length) return <Absent label="No projects" />;

  return (
    <span className="min-w-0 truncate">
      {account.projects
        .map((project) => project.name ?? "Unnamed project")
        .join(", ")}
    </span>
  );
}

function AccountRow({
  account,
  checked,
  columnOrder,
  columnWidths,
  density,
  onToggle,
  visibleColumns,
}: {
  account: Account;
  checked: boolean;
  columnOrder: AccountColumnKey[];
  columnWidths: AccountColumnWidths;
  density: AccountTableDensity;
  onToggle: () => void;
  visibleColumns: Record<AccountColumnKey, boolean>;
}) {
  const columnOrderIndex = (column: AccountColumnKey) =>
    columnOrder.indexOf(column) + 1;
  const firstScrollableColumn = getFirstScrollableAccountColumn(
    visibleColumns,
    columnOrder,
  );
  const borderForColumn = (column: AccountColumnKey) =>
    column === firstScrollableColumn ? leadingCellBorder : cellBorder;
  const rowHeightClass = densityHeightClasses[density];
  const revenue = formatRevenueBand(account.revenueBand);
  const employees = formatEmployeeCount(account.employeeCount);

  return (
    <div
      className={`${readability.densityTransition} ${rowHeightClass} group isolate grid hover:bg-[var(--clue-background-page)]`}
      data-account-id={account.id}
      role="row"
      style={{
        gridTemplateColumns: accountGridTemplate(
          visibleColumns,
          columnOrder,
          columnWidths,
        ),
      }}
    >
      <div
        className={`sticky left-0 z-20 flex h-full items-center bg-white pr-4 pl-6 group-hover:bg-[var(--clue-background-page)] ${leadingCellBorder}`}
        role="gridcell"
        style={{ order: 0 }}
      >
        <AccountCheckbox
          checked={checked}
          className={
            checked
              ? "opacity-100"
              : "opacity-0 group-hover:opacity-100 group-focus-within:opacity-100"
          }
          label={`Select ${account.name}`}
          onChange={onToggle}
        />
      </div>

      {visibleColumns.company ? (
        <div
          className={`sticky left-14 z-20 h-full min-w-0 overflow-hidden bg-white px-4 group-hover:bg-[var(--clue-background-page)] ${pinnedCellBorder}`}
          role="gridcell"
          style={{ order: columnOrderIndex("company") }}
        >
          <Link
            aria-label={`Open ${account.name} account preview`}
            className="flex h-full min-w-0 items-center gap-2 focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-[#567644]"
            href={`/accounts/${account.id}/preview`}
            prefetch={false}
          >
            <AccountAvatar
              logoUrl={account.logoUrl}
              name={account.name}
              size={16}
            />
            <span className={`${readability.uiMedium} truncate`}>{account.name}</span>
            <span className="ml-auto flex size-5 items-center justify-center opacity-0 group-hover:opacity-100 group-focus-within:opacity-100">
              <DesignIcon name="arrow-up-right" size={12} />
            </span>
          </Link>
        </div>
      ) : null}

      {visibleColumns.research ? (
        <div
          className={`flex h-full items-center px-4 ${borderForColumn("research")}`}
          role="gridcell"
          style={{ order: columnOrderIndex("research") }}
        >
          <ResearchStatusCell account={account} />
        </div>
      ) : null}
      {visibleColumns.score ? (
        <div
          className={`flex h-full items-center gap-1 px-4 ${borderForColumn("score")}`}
          role="gridcell"
          style={{ order: columnOrderIndex("score") }}
        >
          <FitScoreCell account={account} />
        </div>
      ) : null}
      {visibleColumns.revenue ? (
        <div
          className={`flex h-full items-center px-4 ${borderForColumn("revenue")}`}
          role="gridcell"
          style={{ order: columnOrderIndex("revenue") }}
        >
          {revenue ?? <Absent />}
        </div>
      ) : null}
      {visibleColumns.size ? (
        <div
          className={`flex h-full items-center px-4 ${borderForColumn("size")}`}
          role="gridcell"
          style={{ order: columnOrderIndex("size") }}
        >
          {employees ?? <Absent />}
        </div>
      ) : null}
      {visibleColumns.projects ? (
        <div
          className={`flex h-full items-center overflow-hidden px-4 ${borderForColumn("projects")}`}
          role="gridcell"
          style={{ order: columnOrderIndex("projects") }}
        >
          <ProjectsCell account={account} />
        </div>
      ) : null}
    </div>
  );
}

interface AccountsTableProps {
  accounts: Account[];
  columnOrder: AccountColumnKey[];
  columnWidths?: AccountColumnWidths;
  density: AccountTableDensity;
  onColumnResize: (column: AccountColumnKey, width: number) => void;
  onColumnResizeReset: (column: AccountColumnKey) => void;
  onToggleAccount: (accountId: string) => void;
  onToggleAll: () => void;
  selectedAccountIds: Set<string>;
  visibleColumns?: Record<AccountColumnKey, boolean>;
}

export function AccountsTable({
  accounts,
  columnOrder,
  columnWidths = defaultAccountColumnWidths,
  density,
  onColumnResize,
  onColumnResizeReset,
  onToggleAccount,
  onToggleAll,
  selectedAccountIds,
  visibleColumns = defaultAccountColumns,
}: AccountsTableProps) {
  const allSelected =
    accounts.length > 0 &&
    accounts.every((account) => selectedAccountIds.has(account.id));

  const columnOrderIndex = (column: AccountColumnKey) =>
    columnOrder.indexOf(column) + 1;
  const firstScrollableColumn = getFirstScrollableAccountColumn(
    visibleColumns,
    columnOrder,
  );

  return (
    <div
      aria-label="Accounts"
      className={`${readability.uiRegular} isolate`}
      role="grid"
      style={{ minWidth: accountTableMinWidth(visibleColumns, columnWidths) }}
    >
      <div
        className="sticky top-0 z-10 isolate grid h-[var(--clue-ds-product-dimension-table-header-height)] bg-white"
        role="row"
        style={{
          gridTemplateColumns: accountGridTemplate(
            visibleColumns,
            columnOrder,
            columnWidths,
          ),
        }}
      >
        <div
          className={`sticky left-0 z-40 flex h-[var(--clue-ds-product-dimension-table-header-height)] items-center bg-white pr-4 pl-6 ${leadingHeaderBorder}`}
          role="columnheader"
          style={{ order: 0 }}
        >
          <AccountCheckbox
            checked={allSelected}
            label="Select all visible accounts"
            onChange={onToggleAll}
          />
        </div>
        {visibleColumns.company ? (
          <HeaderCell
            column="company"
            onResize={onColumnResize}
            onReset={onColumnResizeReset}
            order={columnOrderIndex("company")}
            pinned
            width={columnWidths.company}
          />
        ) : null}
        {(["research", "score", "revenue", "size", "projects"] as const).map(
          (column) =>
            visibleColumns[column] ? (
              <HeaderCell
                column={column}
                key={column}
                onResize={onColumnResize}
                onReset={onColumnResizeReset}
                order={columnOrderIndex(column)}
                showLeadingDivider={firstScrollableColumn !== column}
                width={columnWidths[column]}
              />
            ) : null,
        )}
      </div>

      {accounts.length > 0 ? (
        accounts.map((account) => (
          <AccountRow
            account={account}
            checked={selectedAccountIds.has(account.id)}
            columnOrder={columnOrder}
            columnWidths={columnWidths}
            density={density}
            key={account.id}
            onToggle={() => onToggleAccount(account.id)}
            visibleColumns={visibleColumns}
          />
        ))
      ) : (
        <div
          className={`${readability.densityTransition} ${densityHeightClasses[density]} flex items-center border-b-[0.5px] border-[var(--clue-border-table)] px-6 text-[var(--clue-content-subtle)]`}
        >
          No accounts match this search.
        </div>
      )}
    </div>
  );
}
