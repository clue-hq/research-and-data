"use client";

import Image from "next/image";
import Link from "next/link";
import { DesignIcon } from "@/components/ui/design-icon";
import type { Account, ResearchStatus } from "../model/account";
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
import { AccountCheckbox } from "./account-checkbox";
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

const researchStatusLabels: Record<ResearchStatus, string> = {
  not_started: "Not started",
  in_progress: "In progress...",
  fully_enriched: "Fully enriched",
  failed: "Failed",
};

function HeaderCell({
  column,
  icon,
  label,
  onResize,
  onReset,
  order,
  showLeadingDivider = true,
  pinned = false,
  width,
}: {
  column: AccountColumnKey;
  icon: string;
  label: string;
  onResize: (column: AccountColumnKey, width: number) => void;
  onReset: (column: AccountColumnKey) => void;
  order: number;
  showLeadingDivider?: boolean;
  pinned?: boolean;
  width: number;
}) {
  const constraints = accountColumnWidthConstraints[column];

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

function ResearchBadge({ account }: { account: Account }) {
  const showSpinner =
    account.researchStatus === "in_progress" || account.researchIsRefreshing;

  return (
    <span className={`${readability.pillMedium} flex h-6 w-fit items-center gap-2 rounded-xl bg-[var(--clue-background-pressed)] px-2 shadow-[var(--clue-shadow-low)]`}>
      {showSpinner ? <DesignIcon name="spinner" size={12} /> : null}
      <span className="whitespace-nowrap">
        {researchStatusLabels[account.researchStatus]}
      </span>
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
            <Image
              alt=""
              aria-hidden="true"
              className="size-3 shrink-0 object-contain"
              height={12}
              src={account.logoPath}
              width={12}
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
          <ResearchBadge account={account} />
        </div>
      ) : null}
      {visibleColumns.fit ? (
        <div
          className={`flex h-full items-center px-4 ${borderForColumn("fit")}`}
          role="gridcell"
          style={{ order: columnOrderIndex("fit") }}
        >
          <span className={`${readability.pillMedium} rounded-xl bg-[var(--clue-fit-high-background)] px-2 py-1 text-[var(--clue-fit-high-content)]`}>
            {account.overallFit}
          </span>
        </div>
      ) : null}
      {visibleColumns.score ? (
        <div
          className={`flex h-full items-center gap-1 px-4 ${borderForColumn("score")}`}
          role="gridcell"
          style={{ order: columnOrderIndex("score") }}
        >
          <DesignIcon name="progress-75" size={13} />
          <span>{account.fitScore}</span>
        </div>
      ) : null}
      {visibleColumns.revenue ? (
        <div
          className={`flex h-full items-center px-4 ${borderForColumn("revenue")}`}
          role="gridcell"
          style={{ order: columnOrderIndex("revenue") }}
        >
          {account.revenueBand}
        </div>
      ) : null}
      {visibleColumns.size ? (
        <div
          className={`flex h-full items-center px-4 ${borderForColumn("size")}`}
          role="gridcell"
          style={{ order: columnOrderIndex("size") }}
        >
          {account.employeeBand}
        </div>
      ) : null}
      {visibleColumns.locations ? (
        <div
          className={`flex h-full items-center px-4 ${borderForColumn("locations")}`}
          role="gridcell"
          style={{ order: columnOrderIndex("locations") }}
        >
          {account.locationCount}
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
            icon="building"
            label="Company name"
            onResize={onColumnResize}
            onReset={onColumnResizeReset}
            order={columnOrderIndex("company")}
            pinned
            width={columnWidths.company}
          />
        ) : null}
        {visibleColumns.research ? (
          <HeaderCell
            column="research"
            icon="research"
            label="Research status"
            onResize={onColumnResize}
            onReset={onColumnResizeReset}
            order={columnOrderIndex("research")}
            showLeadingDivider={firstScrollableColumn !== "research"}
            width={columnWidths.research}
          />
        ) : null}
        {visibleColumns.fit ? (
          <HeaderCell
            column="fit"
            icon="circle-chevron-down"
            label="Overall fit"
            onResize={onColumnResize}
            onReset={onColumnResizeReset}
            order={columnOrderIndex("fit")}
            showLeadingDivider={firstScrollableColumn !== "fit"}
            width={columnWidths.fit}
          />
        ) : null}
        {visibleColumns.score ? (
          <HeaderCell
            column="score"
            icon="hash"
            label="Fit score"
            onResize={onColumnResize}
            onReset={onColumnResizeReset}
            order={columnOrderIndex("score")}
            showLeadingDivider={firstScrollableColumn !== "score"}
            width={columnWidths.score}
          />
        ) : null}
        {visibleColumns.revenue ? (
          <HeaderCell
            column="revenue"
            icon="hash"
            label="Revenue"
            onResize={onColumnResize}
            onReset={onColumnResizeReset}
            order={columnOrderIndex("revenue")}
            showLeadingDivider={firstScrollableColumn !== "revenue"}
            width={columnWidths.revenue}
          />
        ) : null}
        {visibleColumns.size ? (
          <HeaderCell
            column="size"
            icon="circle-chevron-down"
            label="Size"
            onResize={onColumnResize}
            onReset={onColumnResizeReset}
            order={columnOrderIndex("size")}
            showLeadingDivider={firstScrollableColumn !== "size"}
            width={columnWidths.size}
          />
        ) : null}
        {visibleColumns.locations ? (
          <HeaderCell
            column="locations"
            icon="hash"
            label="Locations"
            onResize={onColumnResize}
            onReset={onColumnResizeReset}
            order={columnOrderIndex("locations")}
            showLeadingDivider={firstScrollableColumn !== "locations"}
            width={columnWidths.locations}
          />
        ) : null}
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
