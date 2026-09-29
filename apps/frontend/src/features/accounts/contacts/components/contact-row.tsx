"use client";

import Link from "../../components/research-link";
import { DesignIcon } from "@/components/ui/design-icon";
import { ContactAvatar } from "../../components/contact-avatar";
import type { AccountContactSummary } from "../../model/account-contact";
import type { AccountTableDensity } from "../../model/account-table-view";
import { applyEmailLookupToContact } from "../../model/contact-email-lookup";
import readability from "../../components/account-readability.module.css";
import components from "../../components/account-components.module.css";
import { useEmailLookupController } from "../hooks/use-email-lookup-controller";
import { LookupEmailButton } from "./lookup-email-button";

const personaColors = {
  blue: "bg-[var(--clue-ds-color-badge-bg-blue)] text-[var(--clue-ds-color-badge-content-blue)]",
  cyan: "bg-[var(--clue-ds-color-badge-bg-cyan)] text-[var(--clue-ds-color-badge-content-cyan)]",
  green: "bg-[var(--clue-ds-color-badge-bg-green)] text-[var(--clue-ds-color-badge-content-green)]",
  olive: "bg-[var(--clue-ds-color-badge-bg-grass)] text-[var(--clue-ds-color-badge-content-grass)]",
  orange: "bg-[var(--clue-ds-color-badge-bg-orange)] text-[var(--clue-ds-color-badge-content-orange)]",
  pink: "bg-[var(--clue-ds-color-badge-bg-pink)] text-[var(--clue-ds-color-badge-content-pink)]",
  red: "bg-[var(--clue-ds-color-badge-bg-red)] text-[var(--clue-ds-color-badge-content-red)]",
} as const;

const socialPaths = {
  facebook: "/logos/facebook.svg",
  instagram: "/logos/instagram.svg",
  linkedin: "/logos/linkedin.svg",
  whatsapp: "/logos/whatsapp.svg",
  x: "/logos/x.svg",
} as const;

const densityHeightClasses: Record<AccountTableDensity, string> = {
  compact: "h-[var(--clue-ds-product-dimension-table-row-compact)]",
  comfortable: "h-[var(--clue-ds-product-dimension-table-row-comfortable)]",
  spacious: "h-[var(--clue-ds-product-dimension-table-row-spacious)]",
};

export function ContactRow({
  accountId,
  contact,
  density,
  gridTemplateColumns,
  onPreview,
}: {
  accountId: string;
  contact: AccountContactSummary;
  density: AccountTableDensity;
  gridTemplateColumns: string;
  onPreview?: () => void | Promise<void>;
}) {
  // The row shows a looked-up address exactly when the backend resolved one;
  // until then the control does the talking.
  const emailLookup = useEmailLookupController({
    accountId,
    contactId: contact.id,
  });
  const shownContact = applyEmailLookupToContact(contact, emailLookup.result);
  const nameCellClassName =
    "sticky left-14 z-20 flex min-w-0 items-center gap-2 overflow-hidden border-r-[0.5px] border-[var(--clue-border-table)] bg-[var(--clue-background-neutral)] px-4 text-left outline-none group-hover:bg-[var(--clue-background-page)] focus-visible:shadow-[inset_0_0_0_2px_var(--clue-ds-color-components-button-focus-ring)]";
  const nameCell = (
    <>
      <ContactAvatar
        name={contact.name}
        size={24}
        src={contact.avatarUrl}
      />
      <span className={`${readability.uiMedium} truncate`}>{contact.name}</span>
      {contact.profileAction !== "none" ? (
        <span className="ml-auto opacity-0 transition-opacity group-hover:opacity-100">
          <DesignIcon name="arrow-up-right" size={12} />
        </span>
      ) : null}
    </>
  );

  return (
    <div
      className={`${readability.uiRegular} ${readability.densityTransition} ${densityHeightClasses[density]} group isolate grid border-b-[0.5px] border-[var(--clue-border-table)] hover:bg-[var(--clue-background-page)]`}
      role="row"
      style={{ gridTemplateColumns }}
    >
      <div className="sticky left-0 z-30 flex items-center justify-center border-r-[0.5px] border-[var(--clue-border-table)] bg-white group-hover:bg-[var(--clue-background-page)]">
        <input
          aria-label={`Select ${contact.name}`}
          className="size-4 appearance-none rounded-[var(--clue-ds-product-component-button-md-radius)] border-[0.5px] border-[var(--clue-border-neutral)] bg-[var(--clue-background-neutral)] checked:border-[var(--clue-ds-color-border-brand-default)] checked:bg-[var(--clue-ds-color-bg-brand)] focus-visible:outline-none focus-visible:shadow-[var(--clue-ds-product-component-button-effect-focus-transparent)]"
          type="checkbox"
        />
      </div>
      {contact.profileAction === "page" ? (
        <Link
          className={nameCellClassName}
          href={`/accounts/${accountId}/contacts/${contact.id}`}
        >
          {nameCell}
        </Link>
      ) : contact.profileAction === "preview" && onPreview ? (
        <button
          className={nameCellClassName}
          onClick={onPreview}
          type="button"
        >
          {nameCell}
        </button>
      ) : (
        <div className={nameCellClassName}>{nameCell}</div>
      )}
      <div className="flex items-center border-r-[0.5px] border-[var(--clue-border-table)] px-4">
        {/* Ruling S7: no title claim is an em dash, never an invented title. */}
        <span className="truncate">
          {contact.title ?? (
            <span className="text-[var(--clue-content-disabled)]">—</span>
          )}
        </span>
      </div>
      <div className="flex items-center border-r-[0.5px] border-[var(--clue-border-table)] px-4">
        <span
          className={`${readability.pillMedium} ${components.badge} ${personaColors[contact.personaTone]}`}
        >
          {contact.persona}
        </span>
      </div>
      <div className="flex items-center border-r-[0.5px] border-[var(--clue-border-table)] px-4">
        {contact.influence ? (
          <span
            className={`${readability.pillMedium} ${components.badge} ${
              contact.influence === "High"
                ? components.badgePositive
                : components.badgeNeutral
            }`}
          >
            {contact.influence}
          </span>
        ) : (
          "—"
        )}
      </div>
      <div className="flex min-w-0 items-center border-r-[0.5px] border-[var(--clue-border-table)] px-4 text-[var(--clue-content-subtle)]">
        {shownContact.emailLabel ? (
          <a
            className="truncate underline decoration-[var(--clue-border-neutral)] underline-offset-2 hover:text-[var(--clue-content-default)]"
            href={shownContact.outreachEligible === false ? undefined : `mailto:${shownContact.emailLabel}`}
                aria-disabled={shownContact.outreachEligible === false || undefined}
          >
            {shownContact.emailLabel}
          </a>
        ) : (
          <LookupEmailButton controller={emailLookup} />
        )}
      </div>
      <div className="flex items-center gap-2 px-4">
        {contact.socials.map((social) => (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            alt={social}
            className="size-3 object-contain opacity-80"
            key={social}
            src={socialPaths[social]}
          />
        ))}
      </div>
    </div>
  );
}
