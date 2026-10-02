"use client";

import Image from "next/image";
import Link from "next/link";
import { DesignIcon } from "@/components/ui/design-icon";
import type { Account } from "../model/account";
import { isLocalDraftAccount, type AccountRow } from "../model/create-account";
import {
  UNASSIGNED_OWNER_LABEL,
  resolveAccountOwner,
} from "../model/account-owner";
import {
  coreAccountColumnDefinitions,
  defaultAccountColumnWidths,
  defaultAccountColumns,
  getFirstScrollableAccountColumn,
  type AccountColumnDefinition,
  type AccountColumnKey,
  type AccountColumnVisibility,
  type AccountColumnWidths,
  type AccountTableDensity,
} from "../model/account-table-view";
import readability from "./account-readability.module.css";
import components from "./account-components.module.css";
import tableStyles from "./accounts-table.module.css";
import { AccountCheckbox } from "./account-checkbox";
import { AccountColumnIcon } from "./account-column-icon";
import { ColumnResizeHandle } from "./column-resize-handle";
import { ContactAvatar } from "./contact-avatar";
import { FitScoreIndicator } from "./fit-score-indicator";

const densityHeightClasses: Record<AccountTableDensity, string> = {
  compact: "h-[var(--clue-ds-product-dimension-table-row-compact)]",
  comfortable: "h-[var(--clue-ds-product-dimension-table-row-comfortable)]",
  spacious: "h-[var(--clue-ds-product-dimension-table-row-spacious)]",
};

function accountGridTemplate(
  visibleColumns: AccountColumnVisibility,
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
          ? `minmax(${columnWidths[column] ?? 140}px, 1fr)`
          : `${columnWidths[column] ?? 140}px`,
      ),
    )
    .join(" ");
}

function accountTableMinWidth(
  visibleColumns: AccountColumnVisibility,
  columnOrder: AccountColumnKey[],
  columnWidths: AccountColumnWidths,
) {
  return (
    56 +
    columnOrder.reduce(
      (total, column) =>
        total +
        (visibleColumns[column] ? (columnWidths[column] ?? 140) : 0),
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

const accountDateFormatter = new Intl.DateTimeFormat("en-US", {
  dateStyle: "medium",
  timeZone: "UTC",
});

const industryBadgeTones = [
  components.badgeToneOrange,
  components.badgeToneBlue,
  components.badgeToneCyan,
] as const;

function formatAccountDate(value?: string) {
  return value ? accountDateFormatter.format(new Date(value)) : "—";
}

/** The account glyph the header shows when no logo asset exists (ruling S2). */
const ACCOUNT_GLYPH_PATH = "/icons/building.svg";

function formatWebsiteLabel(value: string) {
  return new URL(value).hostname.replace(/^www\./, "");
}

function HeaderCell({
  definition,
  onResize,
  onReset,
  order,
  showLeadingDivider = true,
  pinned = false,
  width,
}: {
  definition: AccountColumnDefinition;
  onResize: (column: AccountColumnKey, width: number) => void;
  onReset: (column: AccountColumnKey) => void;
  order: number;
  showLeadingDivider?: boolean;
  pinned?: boolean;
  width: number;
}) {
  const { icon, key: column, label, maxWidth, minWidth } = definition;

  return (
    <div
      className={`${tableStyles.textRegular} relative flex min-w-0 h-[var(--clue-ds-product-dimension-table-header-height)] items-center gap-1 px-4 ${
        pinned
          ? pinnedHeaderBorder
          : showLeadingDivider
            ? headerBorder
            : leadingHeaderBorder
      } ${
        pinned
          ? `${tableStyles.pinnedCompany} z-30 bg-white`
          : ""
      }`}
      role="columnheader"
      style={{ order }}
    >
      <AccountColumnIcon name={icon} size={12} />
      <span className="min-w-0 truncate text-[var(--clue-content-neutral)]" title={label}>
        {label}
      </span>
      <ColumnResizeHandle
        label={label}
        max={maxWidth}
        min={minWidth}
        onChange={(nextWidth) => onResize(column, nextWidth)}
        onReset={() => onReset(column)}
        width={width}
      />
    </div>
  );
}

function TableBadge({
  children,
  icon,
  title,
  tone = components.badgeNeutral,
}: {
  children: string;
  icon?: React.ReactNode;
  title?: string;
  tone?: string;
}) {
  return (
    <span className={`${tableStyles.textMedium} ${components.badge} ${tableStyles.badge} ${tone}`} title={title ?? children}>
      {icon ? <span className="flex shrink-0">{icon}</span> : null}
      <span className="min-w-0 truncate">{children}</span>
    </span>
  );
}

function ResearchBadge({ account }: { account: Account }) {
  const showSpinner =
    account.researchStatus === "in_progress" || account.researchIsRefreshing;

  return (
    <TableBadge icon={showSpinner ? <DesignIcon name="spinner" size={12} /> : null}>
      {account.researchStatusLabel ?? account.researchStatus}
    </TableBadge>
  );
}

function AccountTableRow({
  account,
  checked,
  columnDefinitions,
  columnOrder,
  columnWidths,
  density,
  onToggle,
  onOpenAccount,
  selectable,
  visibleColumns,
}: {
  account: AccountRow;
  checked: boolean;
  columnDefinitions: AccountColumnDefinition[];
  columnOrder: AccountColumnKey[];
  columnWidths: AccountColumnWidths;
  density: AccountTableDensity;
  onToggle: () => void;
  onOpenAccount?: (account: Account) => void;
  selectable: boolean;
  visibleColumns: AccountColumnVisibility;
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
        {selectable ? (
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
        ) : null}
      </div>

      {columnDefinitions.map((definition) => {
        if (!visibleColumns[definition.key]) return null;

        if (definition.key === "company") {
          return (
            <div
              className={`${tableStyles.pinnedCompany} z-20 h-full min-w-0 overflow-hidden bg-white px-4 group-hover:bg-[var(--clue-background-page)] ${pinnedCellBorder}`}
              key={definition.key}
              role="gridcell"
              style={{ order: columnOrderIndex(definition.key) }}
            >
              <Link
                aria-label={`Open ${account.name} account preview`}
                className="flex h-full min-w-0 items-center gap-2 focus-visible:outline-none focus-visible:shadow-[inset_0_0_0_2px_var(--clue-ds-color-components-button-focus-ring)]"
                href={`/accounts/${account.id}/preview`}
                onNavigate={onOpenAccount ? (event) => { event.preventDefault(); onOpenAccount(account); } : undefined}
                prefetch={false}
                title={account.name}
              >
                {/* unoptimized: the logo route is session-authenticated behind the BFF —
                    the Next image optimizer's server-side refetch carries no session cookie
                    and would 401 (the gallery card documents the same). */}
                <Image
                  alt=""
                  aria-hidden="true"
                  className="size-6 shrink-0 object-contain"
                  height={24}
                  src={account.logoPath ?? ACCOUNT_GLYPH_PATH}
                  unoptimized={account.logoPath != null}
                  width={24}
                />
                <span className={`${tableStyles.textMedium} truncate`}>
                  {account.name}
                </span>
                {/* Ruling f: a locally created account is a draft, and says so
                    in words. Nothing about it is optimistic — no badge, no
                    spinner, no invented score. */}
                {isLocalDraftAccount(account) ? (
                  <span className="shrink-0 text-[var(--clue-content-disabled)]">
                    Not saved yet
                  </span>
                ) : null}
                <span className="ml-auto flex size-5 shrink-0 items-center justify-center opacity-0 group-hover:opacity-100 group-focus-within:opacity-100">
                  <DesignIcon name="arrow-up-right" size={12} />
                </span>
              </Link>
            </div>
          );
        }

        let content: React.ReactNode = null;
        switch (definition.key) {
          case "owner": {
            const owner = resolveAccountOwner(account);
            content = owner ? (
              <span className="flex min-w-0 items-center gap-2">
                <ContactAvatar
                  name={owner.name}
                  size={22}
                  src={owner.avatarUrl}
                />
                <span className="truncate" title={owner.name}>{owner.name}</span>
              </span>
            ) : (
              <span className="text-[var(--clue-content-disabled)]">{UNASSIGNED_OWNER_LABEL}</span>
            );
            break;
          }
          case "industry":
            content = account.industryLabels.length ? (
              <div className="flex min-w-0 items-center gap-1.5" title={account.industryLabels.join(", ")}>
                {account.industryLabels.map((industry, index) => (
                  <TableBadge
                    tone={industryBadgeTones[index % industryBadgeTones.length]}
                    key={industry}
                    title={industry}
                  >
                    {industry}
                  </TableBadge>
                ))}
              </div>
            ) : (
              <span className="text-[var(--clue-content-disabled)]">—</span>
            );
            break;
          case "research":
            content = <ResearchBadge account={account} />;
            break;
          case "fit":
            content = account.overallFit ? (
              <TableBadge tone={components.badgePositive}>
                {account.overallFit}
              </TableBadge>
            ) : (
              <span className="text-[var(--clue-content-disabled)]">—</span>
            );
            break;
          case "score":
            content = <FitScoreIndicator score={account.fitScore} />;
            break;
          case "revenue":
            content = account.revenueBand;
            break;
          case "headcount":
            content = (
              <TableBadge>
                {account.employeeBand}
              </TableBadge>
            );
            break;
          case "locations":
            content = account.locationsLabel ?? account.locationCount;
            break;
          case "website":
            content = account.websiteUrl ? (
              <a
                className="truncate underline decoration-[var(--clue-content-subtle)] underline-offset-2"
                href={account.websiteUrl}
                rel="noreferrer"
                target="_blank"
                title={formatWebsiteLabel(account.websiteUrl)}
              >
                {formatWebsiteLabel(account.websiteUrl)}
              </a>
            ) : (
              <span className="text-[var(--clue-content-disabled)]">—</span>
            );
            break;
          case "linkedin":
          case "twitter":
          case "facebook":
          case "instagram": {
            const social = account.socials.find(
              (item) => item.label.toLowerCase() === definition.key,
            );
            content = social ? (
              <a
                className="truncate underline decoration-[var(--clue-content-subtle)] underline-offset-2"
                href={social.url}
                rel="noreferrer"
                target="_blank"
                title={social.label}
              >
                {social.label}
              </a>
            ) : (
              <span className="text-[var(--clue-content-disabled)]">—</span>
            );
            break;
          }
          case "created":
            content = formatAccountDate(account.createdAt);
            break;
          case "modified":
            content = formatAccountDate(account.lastModifiedAt);
            break;
          default: {
            const variable = account.customFields.find(
              (item) => item.id === definition.variableId,
            );
            if (!variable) {
              content = (
                <span className="text-[var(--clue-content-disabled)]">—</span>
              );
            } else if (variable.presentation === "score") {
              // The backend always serves a numeric string for a score field;
              // anything else is printed as served rather than read as zero.
              const score = Number(variable.value);
              content = Number.isFinite(score) ? (
                <FitScoreIndicator score={score} />
              ) : (
                variable.value
              );
            } else if (variable.presentation === "badge") {
              content = (
                <TableBadge tone={
                  variable.value === "High"
                    ? components.badgePositive
                    : components.badgeNeutral
                }>
                  {variable.value}
                </TableBadge>
              );
            } else {
              content = variable.value;
            }
          }
        }

        return (
          <div
            className={`flex h-full min-w-0 items-center px-4 ${borderForColumn(definition.key)}`}
            key={definition.key}
            role="gridcell"
            style={{ order: columnOrderIndex(definition.key) }}
          >
            <div className={tableStyles.cell}>
              {typeof content === "string" || typeof content === "number" ? (
                <span className="min-w-0 truncate" title={String(content)}>{content}</span>
              ) : content}
            </div>
          </div>
        );
      })}
    </div>
  );
}

interface AccountsTableProps {
  /** Given, a row opens a contextual preview instead of navigating. */
  onOpenAccount?: (account: Account) => void;
  label?: string;
  accounts: AccountRow[];
  columnDefinitions?: AccountColumnDefinition[];
  columnOrder: AccountColumnKey[];
  columnWidths?: AccountColumnWidths;
  density: AccountTableDensity;
  onColumnResize: (column: AccountColumnKey, width: number) => void;
  onColumnResizeReset: (column: AccountColumnKey) => void;
  onToggleAccount: (accountId: string) => void;
  onToggleAll: () => void;
  /** Ids a bulk action can name; a local draft is not one of them. */
  selectableAccountIds?: Set<string>;
  selectedAccountIds: Set<string>;
  visibleColumns?: AccountColumnVisibility;
}

export function AccountsTable({
  onOpenAccount,
  label = "Accounts",
  accounts,
  columnDefinitions = coreAccountColumnDefinitions,
  columnOrder,
  columnWidths = defaultAccountColumnWidths,
  density,
  onColumnResize,
  onColumnResizeReset,
  onToggleAccount,
  onToggleAll,
  selectableAccountIds,
  selectedAccountIds,
  visibleColumns = defaultAccountColumns,
}: AccountsTableProps) {
  const isSelectable = (account: AccountRow) =>
    selectableAccountIds
      ? selectableAccountIds.has(account.id)
      : !isLocalDraftAccount(account);
  const selectable = accounts.filter(isSelectable);
  const allSelected =
    selectable.length > 0 &&
    selectable.every((account) => selectedAccountIds.has(account.id));

  const columnOrderIndex = (column: AccountColumnKey) =>
    columnOrder.indexOf(column) + 1;
  const firstScrollableColumn = getFirstScrollableAccountColumn(
    visibleColumns,
    columnOrder,
  );

  return (
    <div
      aria-label={label}
      className={`${tableStyles.textRegular} isolate`}
      role="grid"
      style={{
        minWidth: accountTableMinWidth(
          visibleColumns,
          columnOrder,
          columnWidths,
        ),
      }}
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
            indeterminate={!allSelected && accounts.some((account) => selectedAccountIds.has(account.id))}
            label="Select all visible accounts"
            onChange={onToggleAll}
          />
        </div>
        {columnDefinitions.map((definition) =>
          visibleColumns[definition.key] ? (
            <HeaderCell
              definition={definition}
              key={definition.key}
              onResize={onColumnResize}
              onReset={onColumnResizeReset}
              order={columnOrderIndex(definition.key)}
              pinned={definition.key === "company"}
              showLeadingDivider={
                firstScrollableColumn !== definition.key
              }
              width={columnWidths[definition.key] ?? definition.width}
            />
          ) : null,
        )}
      </div>

      {accounts.length > 0 ? (
        accounts.map((account) => (
          <AccountTableRow
            account={account}
            checked={selectedAccountIds.has(account.id)}
            columnDefinitions={columnDefinitions}
            columnOrder={columnOrder}
            columnWidths={columnWidths}
            density={density}
            key={account.id}
            onToggle={() => onToggleAccount(account.id)}
            onOpenAccount={onOpenAccount}
            selectable={isSelectable(account)}
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
