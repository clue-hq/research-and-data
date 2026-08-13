"use client";

import Link from "next/link";
import { ApplicationShell } from "@/components/shell/application-shell";
import { AddToChatDialog } from "@/features/projects/components/add-to-chat-dialog";
import { useAddToChatController } from "@/features/projects/hooks/use-add-to-chat-controller";
import type { Account, AccountsResponse } from "../model/account";
import type { AccountDetail } from "../model/account-detail";
import type { AccountBulkCapabilities } from "../model/bulk-actions";
import { ACCOUNT_RECOVERY_COPY } from "../model/account-recovery";
import { useAccountsScreenController } from "../hooks/use-accounts-screen-controller";
import readability from "./account-readability.module.css";
import { AccountPreviewDrawer } from "./account-preview-drawer";
import { AccountsTable } from "./accounts-table";
import { AccountsToolbar } from "./accounts-toolbar";
import { TablePagination } from "./table-pagination";

export function AccountsScreen({
  accounts,
  bulkCapabilities,
  meta,
  previewAccount,
}: {
  accounts: Account[];
  bulkCapabilities: AccountBulkCapabilities;
  meta: AccountsResponse["meta"];
  previewAccount?: AccountDetail;
}) {
  const controller = useAccountsScreenController(
    accounts,
    meta,
    bulkCapabilities,
  );
  const selectedCount = controller.selectedAccountIds.size;
  const overAddToProjectLimit =
    selectedCount > controller.bulkCapabilities.addToProject.maxItems;
  const overAddToChatLimit =
    selectedCount > controller.bulkCapabilities.addToChat.maxItems;
  const addToChat = useAddToChatController({
    contextRefs: [...controller.selectedAccountIds].map((accountId) => ({
      objectId: accountId,
      objectType: "account" as const,
      version: null,
    })),
    onTransferred: controller.clearSelection,
    source: "accounts",
  });

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

        {selectedCount > 0 ? (
          <div
            aria-label="Account bulk actions"
            className={`${readability.uiRegular} flex min-h-11 shrink-0 flex-wrap items-center gap-3 border-b-[0.5px] border-[var(--clue-border-table)] bg-[var(--clue-background-hover)] px-6 py-2`}
          >
            <span className={readability.uiMedium}>{selectedCount} selected</span>
            {controller.bulkCapabilities.addToProject.allowed ? <select
              aria-label="Project for selected Accounts"
              className="h-7 min-w-48 rounded-md border-[0.5px] border-[var(--clue-border-input)] bg-white px-2"
              onChange={(event) =>
                controller.setSelectedProjectId(event.target.value)
              }
              value={controller.selectedProjectId}
            >
              {controller.bulkCapabilities.projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select> : null}
            {controller.bulkCapabilities.addToProject.allowed ? <button
              className={`${readability.actionMedium} h-7 rounded-md bg-[var(--clue-content-neutral)] px-3 text-white disabled:cursor-not-allowed disabled:opacity-50`}
              disabled={
                overAddToProjectLimit ||
                controller.isBulkSubmitting ||
                !controller.selectedProjectId
              }
              onClick={controller.executeAddToProject}
              type="button"
            >
              {controller.isBulkSubmitting ? "Adding…" : "Add to project"}
            </button> : null}
            {controller.chatHandoffAvailable && controller.bulkCapabilities.addToChat.allowed ? (
              <button
                className={`${readability.actionMedium} h-7 rounded-md border-[0.5px] border-[var(--clue-border-input)] bg-white px-3 disabled:cursor-not-allowed disabled:opacity-50`}
                disabled={overAddToChatLimit || addToChat.submitting}
                onClick={addToChat.show}
                type="button"
              >
                Add to chat
              </button>
            ) : null}
            <button
              className={`${readability.actionMedium} h-7 rounded-md px-2 hover:bg-white`}
              onClick={controller.clearSelection}
              type="button"
            >
              Clear
            </button>
            {overAddToProjectLimit && controller.bulkCapabilities.addToProject.allowed ? (
              <span role="alert" className="text-[var(--clue-content-subtle)]">
                Select at most {controller.bulkCapabilities.addToProject.maxItems} Accounts.
              </span>
            ) : null}
          </div>
        ) : null}

        {controller.bulkNotice ? (
          <div
            aria-live="polite"
            className={`${readability.uiRegular} flex min-h-9 items-center justify-between gap-3 border-b-[0.5px] border-[var(--clue-border-table)] px-6 py-1.5 text-[var(--clue-content-subtle)]`}
          >
            <span>{controller.bulkNotice}</span>
            <button
              className="underline"
              onClick={controller.clearBulkNotice}
              type="button"
            >
              Dismiss
            </button>
          </div>
        ) : null}

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
            selectableAccountIds={controller.selectableAccountIds}
            selectionEnabled={controller.selectionEnabled}
            visibleColumns={controller.visibleColumns}
            workspaceIsEmpty={
              controller.totalCount === 0 && !controller.hasActiveFilter
            }
          />
        </div>

        {controller.loadRecovery ? (
          <div
            className={`${readability.uiRegular} border-t-[0.5px] border-[var(--clue-border-table)] px-6 py-2 text-[var(--clue-content-subtle)]`}
            role="alert"
          >
            {ACCOUNT_RECOVERY_COPY[controller.loadRecovery.kind].title}.{" "}
            {controller.loadRecovery.kind === "session_expired" ? (
              <Link className="underline" href="/sign-in?reason=session_expired">
                Sign in
              </Link>
            ) : controller.loadRecovery.kind === "workspace_selection" ? (
              <a className="underline" href="#clue-workspace-selector">
                Choose workspace
              </a>
            ) : controller.loadRecovery.kind === "forbidden" ? (
              <Link
                className="underline"
                href="/access-denied?code=WORKSPACE_FORBIDDEN"
              >
                View access options
              </Link>
            ) : controller.loadRecovery.kind === "contract_error" ? (
              "Contact support."
            ) : (
              "Use the page controls to try again."
            )}
          </div>
        ) : null}

        <TablePagination
          currentCount={controller.visibleAccounts.length}
          isLoading={controller.isPageLoading}
          onPageChange={controller.loadPage}
          onPageSizeChange={(nextPageSize) =>
            controller.loadPage(1, nextPageSize)
          }
          page={controller.page}
          pageSize={controller.pageSize}
          totalItems={controller.totalCount}
          totalPages={controller.totalPages}
          summary={
            controller.hasActiveFilter
              ? `${controller.visibleAccounts.length} matching rows on this page · ${controller.totalCount} total Accounts`
              : undefined
          }
        />
        <AddToChatDialog
          controller={addToChat}
          selectedCount={selectedCount}
          subjectLabel="Accounts"
        />
      </main>
      {previewAccount ? <AccountPreviewDrawer account={previewAccount} /> : null}
    </ApplicationShell>
  );
}
