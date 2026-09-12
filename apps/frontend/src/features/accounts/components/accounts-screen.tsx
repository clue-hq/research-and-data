"use client";

import { Button } from "@/components/ui/button";
import { AddToChatDialog } from "@/features/projects/components/add-to-chat-dialog";
import { useAddToChatController } from "@/features/projects/hooks/use-add-to-chat-controller";
import type { Account } from "../model/account";
import type { AccountBulkCapabilities } from "../model/bulk-actions";
import { useAccountsScreenController } from "../hooks/use-accounts-screen-controller";
import { AccountsTable } from "./accounts-table";
import { AccountsToolbar } from "./accounts-toolbar";
import readability from "./account-readability.module.css";
import components from "./account-components.module.css";
import tableStyles from "./accounts-table.module.css";

export function AccountsScreen({
  accounts,
  bulkCapabilities,
}: {
  accounts: Account[];
  bulkCapabilities: AccountBulkCapabilities;
}) {
  const controller = useAccountsScreenController(accounts, bulkCapabilities);
  // What the bar counts and the actions submit is the selection still on screen:
  // a row hidden by the current search/filter keeps its checkbox but is not
  // acted on (the selection itself survives — searching is not deselecting).
  const selectedCount = controller.visibleSelectedAccountIds.size;
  const overAddToProjectLimit =
    selectedCount > controller.bulkCapabilities.addToProject.maxItems;
  const overAddToChatLimit =
    selectedCount > controller.bulkCapabilities.addToChat.maxItems;
  const addToChat = useAddToChatController({
    contextRefs: [...controller.visibleSelectedAccountIds].map((accountId) => ({
      objectId: accountId,
      objectType: "account" as const,
      version: null,
    })),
    onTransferred: controller.clearSelection,
    source: "accounts",
  });

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

        {/* The two bulk actions the table has (founder ruling b): add the
            selection to a project, or carry it into a chat. There is no bulk
            email lookup — that action lives on the single contact row. */}
        {selectedCount > 0 ? (
          <div
            aria-label="Account bulk actions"
            className={`${readability.uiRegular} ${tableStyles.selectionBar}`}
          >
            <span className={readability.uiMedium}>{selectedCount} selected</span>
            {controller.bulkCapabilities.addToProject.allowed ? (
              <>
                <select
                  aria-label="Project for selected Accounts"
                  className={`${components.input} min-w-48 px-2`}
                  disabled={controller.isBulkSubmitting}
                  onChange={(event) =>
                    controller.setSelectedProjectId(event.target.value)
                  }
                  value={controller.selectedProjectId}
                >
                  <option disabled value="">Choose a project</option>
                  {controller.bulkCapabilities.projects.map((project) => (
                    <option key={project.id} value={project.id}>
                      {project.name}
                    </option>
                  ))}
                </select>
                <Button
                  disabled={
                    overAddToProjectLimit ||
                    controller.isBulkSubmitting ||
                    !controller.selectedProjectId
                  }
                  onClick={controller.executeAddToProject}
                  size="md"
                  type="button"
                >
                  {controller.isBulkSubmitting ? "Adding…" : "Add to project"}
                </Button>
              </>
            ) : null}
            {controller.chatHandoffAvailable &&
            controller.bulkCapabilities.addToChat.allowed ? (
              <Button
                disabled={overAddToChatLimit || addToChat.submitting}
                onClick={addToChat.show}
                size="md"
                type="button"
                variant="transparent"
              >
                Add to chat
              </Button>
            ) : null}
            <Button
              onClick={controller.clearSelection}
              size="md"
              type="button"
              variant="transparent"
            >
              Clear
            </Button>
            {overAddToProjectLimit &&
            controller.bulkCapabilities.addToProject.allowed ? (
              <span
                className="text-[var(--clue-content-subtle)]"
                role="alert"
              >
                Select at most{" "}
                {controller.bulkCapabilities.addToProject.maxItems} Accounts.
              </span>
            ) : null}
          </div>
        ) : null}

        {controller.bulkNotice ? (
          <div
            aria-live="polite"
            className={`${readability.uiRegular} ${tableStyles.selectionNotice}`}
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
            selectableAccountIds={controller.selectableAccountIds}
            selectedAccountIds={controller.selectedAccountIds}
            visibleColumns={controller.visibleColumns}
          />
        </div>
        <AddToChatDialog
          controller={addToChat}
          selectedCount={selectedCount}
          subjectLabel="Accounts"
        />
      </main>
  );
}
