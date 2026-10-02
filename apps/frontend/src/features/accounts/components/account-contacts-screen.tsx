"use client";
import motion from "./account-motion.module.css";

import { AccountDetailsList } from "./account-detail-primitives";
import { DesignIcon } from "@/components/ui/design-icon";
import {
  AccountDetailsRail,
  AccountWorkspaceShell,
} from "./account-workspace-shell";
import { ContactPreview } from "../contacts/components/contact-preview";
import { ContactRow } from "../contacts/components/contact-row";
import { useAccountContactsController } from "../contacts/hooks/use-account-contacts-controller";
import type { AccountContactSummary } from "../model/account-contact";
import type { AccountDetail } from "../model/account-detail";
import readability from "./account-readability.module.css";
import components from "./account-components.module.css";
import { TableDensitySelector } from "./table-density-selector";
import { ColumnResizeHandle } from "./column-resize-handle";
import {
  contactColumnOrder,
  contactColumnWidthConstraints,
  type ContactColumnKey,
  type ContactColumnWidths,
} from "../model/contact-table-view";

const headers: Array<{
  key: ContactColumnKey;
  label: string;
}> = [
  { key: "name", label: "Contact name" },
  { key: "title", label: "Title" },
  { key: "persona", label: "Persona" },
  { key: "influence", label: "Influence" },
  { key: "email", label: "Email" },
  { key: "social", label: "Social" },
];

function contactGridTemplate(columnWidths: ContactColumnWidths) {
  return ["56px"]
    .concat(
      contactColumnOrder.map((column, index) =>
        index === contactColumnOrder.length - 1
          ? `minmax(${columnWidths[column]}px, 1fr)`
          : `${columnWidths[column]}px`,
      ),
    )
    .join(" ");
}

function contactTableMinWidth(columnWidths: ContactColumnWidths) {
  return (
    56 +
    contactColumnOrder.reduce(
      (total, column) => total + columnWidths[column],
      0,
    )
  );
}

export function AccountContactsScreen({
  account,
  contacts,
}: {
  account: AccountDetail;
  contacts: AccountContactSummary[];
}) {
  const [controller, displayControlsRef] =
    useAccountContactsController(account.id, contacts);

  return (
    <AccountWorkspaceShell account={account} activeTab="contacts">
      <div className="flex h-full min-h-0 min-w-0">
        <section className={`${motion.pageEntry} flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden`}>
          <div className="flex h-[var(--clue-ds-product-dimension-header-action-bar-height)] shrink-0 items-center justify-between border-b-[0.5px] border-[var(--clue-border-table)] px-6">
            <h1 className={readability.pageTitle}>Contacts</h1>
            <div className="flex items-center gap-2">
              <label className={`${components.input} flex w-56 items-center gap-1.5 px-2.5 max-md:hidden`}>
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
                  className={`${readability.actionMedium} flex h-[var(--clue-ds-product-component-button-sm-height)] items-center gap-[var(--clue-ds-product-component-button-gap)] rounded-[var(--clue-ds-product-component-button-sm-radius)] px-[var(--clue-ds-product-component-button-sm-padding-inline)] hover:bg-[var(--clue-background-hover)]`}
                  onClick={controller.toggleDisplay}
                  type="button"
                >
                  <DesignIcon name="settings" size={12} />
                  Display
                </button>
                {controller.displayOpen ? (
                  <section className={`${readability.popoverEnter} ${components.popover} absolute top-9 right-0 z-30 w-[300px] p-3`}>
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
          <div className="min-h-0 flex-1 overflow-auto">
            <div
              aria-label="Account contacts"
              className={readability.uiRegular}
              role="grid"
              style={{
                minWidth: contactTableMinWidth(controller.columnWidths),
              }}
            >
              <div
                className={`${readability.uiRegular} sticky top-0 z-20 grid h-[var(--clue-ds-product-dimension-table-header-height)] bg-white`}
                role="row"
                style={{
                  gridTemplateColumns: contactGridTemplate(
                    controller.columnWidths,
                  ),
                }}
              >
                <div
                  className="sticky left-0 z-40 flex items-center justify-center border-b-[0.5px] border-r-[0.5px] border-[var(--clue-border-table)] bg-white"
                  role="columnheader"
                >
                  <input
                    aria-label="Select all contacts"
                    className="size-4 appearance-none rounded-[var(--clue-ds-product-component-button-md-radius)] border-[0.5px] border-[var(--clue-border-neutral)] bg-[var(--clue-background-neutral)] checked:border-[var(--clue-ds-color-border-brand-default)] checked:bg-[var(--clue-ds-color-bg-brand)] focus-visible:outline-none focus-visible:shadow-[var(--clue-ds-product-component-button-effect-focus-transparent)]"
                    type="checkbox"
                  />
                </div>
                {headers.map((header) => {
                  const constraints =
                    contactColumnWidthConstraints[header.key];
                  const pinned = header.key === "name";

                  return (
                  <div
                    className={`relative flex items-center border-b-[0.5px] border-r-[0.5px] border-[var(--clue-border-table)] bg-white px-4 ${
                      pinned
                        ? "sticky left-14 z-30 overflow-hidden"
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
              {controller.visibleContacts.map((contact) => (
                <ContactRow
                  accountId={account.id}
                  contact={contact}
                  density={controller.density}
                  gridTemplateColumns={contactGridTemplate(
                    controller.columnWidths,
                  )}
                  key={contact.id}
                  onPreview={() => controller.openPreview(contact.id)}
                />
              ))}
            </div>
          </div>
        </section>
        <AccountDetailsRail>
          <section className="border-b border-[var(--clue-border-neutral)] px-4 py-[22px]">
            <h2 className={readability.sectionHeading}>
              Account details
            </h2>
            <div className="mt-6">
              <AccountDetailsList account={account} />
            </div>
          </section>
        </AccountDetailsRail>
      </div>
      {controller.previewContact ? (
        <ContactPreview
          accountId={account.id}
          contact={controller.previewContact}
          onClose={controller.closePreview}
        />
      ) : null}
    </AccountWorkspaceShell>
  );
}
