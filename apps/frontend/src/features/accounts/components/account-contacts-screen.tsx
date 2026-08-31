"use client";

import { AccountDetailsList } from "./account-detail-primitives";
import { AddToChatDialog } from "@/features/projects/components/add-to-chat-dialog";
import { useAddToChatController } from "@/features/projects/hooks/use-add-to-chat-controller";
import { DesignIcon } from "@/components/ui/design-icon";
import {
  AccountDetailsRail,
  AccountWorkspaceShell,
} from "./account-workspace-shell";
import { ContactRow } from "../contacts/components/contact-row";
import { useAccountContactsController } from "../contacts/hooks/use-account-contacts-controller";
import type { AccountContactSummary } from "../model/account-contact";
import type { AccountDetail } from "../model/account-detail";
import type { ContactBulkCapabilities } from "../model/bulk-actions";
import readability from "./account-readability.module.css";
import { TableDensitySelector } from "./table-density-selector";
import { ColumnResizeHandle } from "./column-resize-handle";
import {
  contactColumnOrder,
  contactColumnWidthConstraints,
  type ContactColumnKey,
  type ContactColumnWidths,
} from "../model/contact-table-view";
import { AccountCheckbox } from "./account-checkbox";
import { TablePagination } from "./table-pagination";

const headers: Array<{
  key: ContactColumnKey;
  label: string;
}> = [
  { key: "name", label: "Contact name" },
  { key: "title", label: "Title" },
  { key: "persona", label: "Persona" },
  { key: "role", label: "Committee role" },
  { key: "signals", label: "Signals" },
  { key: "email", label: "Email" },
  { key: "social", label: "Social" },
];

function contactGridTemplate(
  columnWidths: ContactColumnWidths,
  selectionEnabled: boolean,
) {
  return (selectionEnabled ? ["56px"] : [])
    .concat(
      contactColumnOrder.map((column, index) =>
        index === contactColumnOrder.length - 1
          ? `minmax(${columnWidths[column]}px, 1fr)`
          : `${columnWidths[column]}px`,
      ),
    )
    .join(" ");
}

function contactTableMinWidth(
  columnWidths: ContactColumnWidths,
  selectionEnabled: boolean,
) {
  return (
    (selectionEnabled ? 56 : 0) +
    contactColumnOrder.reduce(
      (total, column) => total + columnWidths[column],
      0,
    )
  );
}

export function AccountContactsScreen({
  account,
  bulkCapabilities,
  contacts,
}: {
  account: AccountDetail;
  bulkCapabilities: ContactBulkCapabilities;
  contacts: AccountContactSummary[];
}) {
  const [controller, displayControlsRef] =
    useAccountContactsController(
      account.id,
      contacts,
      bulkCapabilities,
    );
  const selectedCount = controller.selectedContactIds.size;
  const overEmailLimit =
    selectedCount > controller.bulkCapabilities.lookupWorkEmails.maxItems;
  const overAddToChatLimit =
    selectedCount > controller.bulkCapabilities.addToChat.maxItems;
  const addToChat = useAddToChatController({
    contextRefs: [...controller.selectedContactIds].map((contactId) => ({
      objectId: contactId,
      objectType: "contact" as const,
      version: null,
    })),
    onTransferred: controller.clearSelection,
    source: "contacts",
  });

  return (
    <AccountWorkspaceShell account={account} activeTab="contacts">
      <div className="flex h-full min-h-0 min-w-0">
        <section className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          <div className="flex h-[var(--clue-ds-product-dimension-header-action-bar-height)] shrink-0 items-center justify-between border-b-[0.5px] border-[var(--clue-border-table)] px-6">
            <h1 className={readability.pageTitle}>Contacts</h1>
            <div className="flex items-center gap-2">
              <label className="flex h-[var(--clue-ds-product-dimension-header-search-height)] w-56 items-center gap-1.5 rounded-[7px] border-[0.5px] border-[var(--clue-border-input)] bg-[var(--clue-background-hover)] px-2.5 shadow-[var(--clue-shadow-low)] max-md:hidden">
                <span className="sr-only">Search contacts</span>
                <DesignIcon name="search" size={12} />
                <input
                  className={`${readability.uiRegular} min-w-0 flex-1 bg-transparent outline-none`}
                  onChange={(event) =>
                    controller.setSearch(event.target.value)
                  }
                  placeholder="Search contacts"
                  value={controller.search}
                />
              </label>
              <div className="relative" ref={displayControlsRef}>
                <button
                  aria-expanded={controller.displayOpen}
                  className={`${readability.actionMedium} flex h-7 items-center gap-1 rounded-md px-2 hover:bg-[var(--clue-background-hover)]`}
                  onClick={controller.toggleDisplay}
                  type="button"
                >
                  <DesignIcon name="settings" size={12} />
                  Display
                </button>
                {controller.displayOpen ? (
                  <section className={`${readability.popoverEnter} absolute top-9 right-0 z-30 w-[300px] rounded-lg border-[0.5px] border-[var(--clue-border-neutral)] bg-white p-3 shadow-[0_8px_24px_rgba(0,24,62,0.10)]`}>
                    <h2 className={`${readability.actionMedium} mb-2 text-[var(--clue-content-subtle)]`}>
                      Row density
                    </h2>
                    <TableDensitySelector
                      density={controller.density}
                      onChange={controller.setDensity}
                    />
                  </section>
                ) : null}
              </div>
            </div>
          </div>
          {selectedCount > 0 ? (
            <div
              aria-label="Contact bulk actions"
              className={`${readability.uiRegular} flex min-h-11 shrink-0 flex-wrap items-center gap-3 border-b-[0.5px] border-[var(--clue-border-table)] bg-[var(--clue-background-hover)] px-6 py-2`}
            >
              <span className={readability.uiMedium}>{selectedCount} selected</span>
              {controller.bulkCapabilities.lookupWorkEmails.allowed ? <button
                className={`${readability.actionMedium} h-7 rounded-md bg-[var(--clue-content-neutral)] px-3 text-white disabled:cursor-not-allowed disabled:opacity-50`}
                disabled={overEmailLimit || controller.isBulkSubmitting}
                onClick={controller.executeEmailLookup}
                type="button"
              >
                {controller.isBulkSubmitting
                  ? "Starting lookups…"
                  : "Look up work emails"}
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
              {overEmailLimit && controller.bulkCapabilities.lookupWorkEmails.allowed ? (
                <span role="alert" className="text-[var(--clue-content-subtle)]">
                  Select at most {controller.bulkCapabilities.lookupWorkEmails.maxItems} Contacts.
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
          <div className="min-h-0 flex-1 overflow-auto">
            <div
              aria-label="Account contacts"
              className={readability.uiRegular}
              role="grid"
              style={{
                minWidth: contactTableMinWidth(
                  controller.columnWidths,
                  controller.selectionEnabled,
                ),
              }}
            >
              <div
                className={`${readability.uiMedium} sticky top-0 z-20 grid h-[var(--clue-ds-product-dimension-table-header-height)] bg-white`}
                role="row"
                style={{
                  gridTemplateColumns: contactGridTemplate(
                    controller.columnWidths,
                    controller.selectionEnabled,
                  ),
                }}
              >
                {controller.selectionEnabled ? (
                  <div
                    className="sticky left-0 z-40 flex items-center justify-center border-b-[0.5px] border-r-[0.5px] border-[var(--clue-border-table)] bg-white"
                    role="columnheader"
                  >
                    <AccountCheckbox
                      checked={
                        controller.visibleContacts.length > 0 &&
                        controller.visibleContacts.every((contact) =>
                          controller.selectedContactIds.has(contact.id),
                        )
                      }
                      indeterminate={
                        controller.visibleContacts.some((contact) =>
                          controller.selectedContactIds.has(contact.id),
                        ) &&
                        !controller.visibleContacts.every((contact) =>
                          controller.selectedContactIds.has(contact.id),
                        )
                      }
                      label="Select all Contacts on this page"
                      onChange={controller.toggleAllVisibleContacts}
                    />
                  </div>
                ) : null}
                {headers.map((header) => {
                  const constraints =
                    contactColumnWidthConstraints[header.key];
                  const pinned = header.key === "name";

                  return (
                  <div
                    className={`relative flex items-center border-b-[0.5px] border-r-[0.5px] border-[var(--clue-border-table)] bg-white px-4 ${
                      pinned
                        ? `sticky ${controller.selectionEnabled ? "left-14" : "left-0"} z-30 overflow-hidden`
                        : ""
                    }`}
                    key={header.key}
                    role="columnheader"
                  >
                    <span className="whitespace-nowrap">{header.label}</span>
                    <ColumnResizeHandle
                      label={header.label}
                      max={constraints.max}
                      min={constraints.min}
                      onChange={(width) =>
                        controller.setColumnWidth(header.key, width)
                      }
                      onReset={() =>
                        controller.resetColumnWidth(header.key)
                      }
                      width={controller.columnWidths[header.key]}
                    />
                  </div>
                  );
                })}
              </div>
              {controller.visibleContacts.length ? (
                controller.visibleContacts.map((contact) => (
                  <ContactRow
                    accountId={account.id}
                    contact={contact}
                    density={controller.density}
                    gridTemplateColumns={contactGridTemplate(
                      controller.columnWidths,
                      controller.selectionEnabled,
                    )}
                    key={contact.id}
                    onToggle={() => controller.toggleContact(contact.id)}
                    selected={controller.selectedContactIds.has(contact.id)}
                    selectionEnabled={controller.selectionEnabled}
                  />
                ))
              ) : (
                <p
                  className={`${readability.uiRegular} px-6 py-6 text-[var(--clue-content-subtle)]`}
                >
                  No committee members have been resolved for this account yet.
                </p>
              )}
            </div>
          </div>
          <TablePagination
            currentCount={controller.visibleContacts.length}
            isLoading={false}
            onPageChange={controller.setPage}
            onPageSizeChange={controller.setPageSize}
            page={controller.page}
            pageSize={controller.pageSize}
            totalItems={controller.filteredCount}
            totalPages={controller.totalPages}
          />
          <AddToChatDialog
            controller={addToChat}
            selectedCount={selectedCount}
            subjectLabel="Contacts"
          />
        </section>
        <AccountDetailsRail className="xl:!w-[410px]">
          <section className="border-b-[0.5px] border-[var(--clue-border-neutral)] p-4">
            <h2 className={readability.sectionHeading}>
              Account details
            </h2>
            <div className="mt-6">
              <AccountDetailsList account={account} />
            </div>
          </section>
        </AccountDetailsRail>
      </div>
    </AccountWorkspaceShell>
  );
}
