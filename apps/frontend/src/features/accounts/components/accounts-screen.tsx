"use client";

import { ApplicationShell } from "@/components/shell/application-shell";
import type { Account } from "../model/account";
import type { AccountDetail } from "../model/account-detail";
import { useAccountsScreenController } from "../hooks/use-accounts-screen-controller";
import { AccountPreviewDrawer } from "./account-preview-drawer";
import { AccountsTable } from "./accounts-table";
import { AccountsToolbar } from "./accounts-toolbar";

export function AccountsScreen({
  accounts,
  previewAccount,
}: {
  accounts: Account[];
  previewAccount?: AccountDetail;
}) {
  const controller = useAccountsScreenController(accounts);

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
      </main>
      {previewAccount ? (
        <AccountPreviewDrawer account={previewAccount} />
      ) : null}
    </ApplicationShell>
  );
}
