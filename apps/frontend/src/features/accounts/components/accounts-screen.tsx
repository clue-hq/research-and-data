"use client";

import type { Account } from "../model/account";
import { useAccountsScreenController } from "../hooks/use-accounts-screen-controller";
import { AccountsTable } from "./accounts-table";
import { AccountsToolbar } from "./accounts-toolbar";
import tableStyles from "./accounts-table.module.css";

export function AccountsScreen({
  accounts,
}: {
  accounts: Account[];
}) {
  const controller = useAccountsScreenController(accounts);

  return (
      <main className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden">
        <AccountsToolbar
          columnDefinitions={controller.columnDefinitions}
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
          researchStatusOptions={controller.researchStatusOptions}
          search={controller.search}
          sort={controller.sort}
          visibleColumns={controller.visibleColumns}
        />
        <div className={`${tableStyles.viewport} clue-scrollbar-hidden min-h-0 min-w-0 flex-1 overflow-auto`}>
          <AccountsTable
            accounts={controller.visibleAccounts}
            columnDefinitions={controller.columnDefinitions}
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
      </main>
  );
}
