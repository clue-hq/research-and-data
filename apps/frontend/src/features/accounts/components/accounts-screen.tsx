"use client";

import { ApplicationShell } from "@/components/shell/application-shell";
import type { Account, AccountsResponse } from "../model/account";
import type { AccountDetail } from "../model/account-detail";
import { useAccountsScreenController } from "../hooks/use-accounts-screen-controller";
import readability from "./account-readability.module.css";
import { AccountPreviewDrawer } from "./account-preview-drawer";
import { AccountsTable } from "./accounts-table";
import { AccountsToolbar } from "./accounts-toolbar";

/**
 * The loaded-vs-total footer.
 *
 * The table holds one keyset page until more is asked for, and the authored
 * filters and search run over the rows it holds — so a filtered count is a
 * count of *loaded* rows, never of the workspace. Saying so is the point: the
 * truncation has to be visible, not silent.
 */
function AccountsFooter({
  filteredCount,
  hasActiveFilter,
  hasMore,
  isLoadingMore,
  loadedCount,
  loadError,
  onLoadMore,
  totalCount,
}: {
  filteredCount: number;
  hasActiveFilter: boolean;
  hasMore: boolean;
  isLoadingMore: boolean;
  loadedCount: number;
  loadError: string | null;
  onLoadMore: () => void;
  totalCount: number;
}) {
  const filtered = filteredCount !== loadedCount;
  // The caveat is about unfetched rows, so it keys on an authored filter plus a
  // page still pending — not on whether the filter excluded anything here. A
  // filter that happens to match every loaded row is precisely the one whose
  // result looks complete and is not.
  const showTruncationCaveat = hasActiveFilter && hasMore;

  return (
    <div
      className={`${readability.uiRegular} flex shrink-0 flex-wrap items-center gap-3 border-t-[0.5px] border-[var(--clue-border-table)] px-6 py-2.5`}
    >
      <span className="text-[var(--clue-content-subtle)]">
        Showing {filtered ? `${filteredCount} of ` : ""}
        {loadedCount} loaded
        {totalCount > loadedCount ? ` of ${totalCount} accounts` : " accounts"}
        {showTruncationCaveat ? " · filters apply to loaded rows only" : ""}
      </span>
      {hasMore ? (
        <button
          className={`${readability.actionMedium} flex h-7 items-center rounded-md border-[0.5px] border-[var(--clue-border-neutral)] px-2.5 hover:bg-[var(--clue-background-hover)] disabled:opacity-60`}
          disabled={isLoadingMore}
          onClick={onLoadMore}
          type="button"
        >
          {isLoadingMore ? "Loading…" : "Load more"}
        </button>
      ) : null}
      {loadError ? (
        <span role="alert" className="text-[var(--clue-content-subtle)]">
          {loadError}
        </span>
      ) : null}
    </div>
  );
}

export function AccountsScreen({
  accounts,
  meta,
  previewAccount,
}: {
  accounts: Account[];
  meta: AccountsResponse["meta"];
  previewAccount?: AccountDetail;
}) {
  const controller = useAccountsScreenController(accounts, meta);

  return (
    <ApplicationShell activeHref="/accounts">
      <main className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden">
        <AccountsToolbar
          columnOrder={controller.columnOrder}
          density={controller.density}
          filters={controller.filters}
          onColumnMove={controller.moveColumn}
          onColumnReorder={controller.reorderColumn}
          onColumnToggle={controller.toggleColumn}
          onCreateAccount={controller.createAccount}
          onDensityChange={controller.setDensity}
          onFiltersChange={controller.setFilters}
          onSearchChange={controller.setSearch}
          onSortChange={controller.setSort}
          projects={controller.projectOptions}
          search={controller.search}
          sort={controller.sort}
          visibleColumns={controller.visibleColumns}
        />
        <div className="clue-scrollbar-hidden min-h-0 min-w-0 flex-1 overflow-auto">
          <AccountsTable
            accounts={controller.visibleAccounts}
            columnOrder={controller.columnOrder}
            columnWidths={controller.columnWidths}
            density={controller.density}
            onColumnResize={controller.setColumnWidth}
            onColumnResizeReset={controller.resetColumnWidth}
            onToggleAccount={controller.toggleAccount}
            onToggleAll={controller.toggleAllVisibleAccounts}
            selectedAccountIds={controller.selectedAccountIds}
            visibleColumns={controller.visibleColumns}
          />
        </div>
        <AccountsFooter
          filteredCount={controller.visibleAccounts.length}
          hasActiveFilter={controller.hasActiveFilter}
          hasMore={controller.hasMore}
          isLoadingMore={controller.isLoadingMore}
          loadedCount={controller.loadedCount}
          loadError={controller.loadError}
          onLoadMore={controller.loadMore}
          totalCount={controller.totalCount}
        />
      </main>
      {previewAccount ? (
        <AccountPreviewDrawer account={previewAccount} />
      ) : null}
    </ApplicationShell>
  );
}
