import Link from "next/link";
import { DesignIcon } from "@/components/ui/design-icon";
import { ContactAvatar } from "../../components/contact-avatar";
import { Absent, Restricted } from "../../components/account-facts";
import {
  contactPersonaLabel,
  contactPersonaTone,
  type AccountContactSummary,
} from "../../model/account-contact";
import {
  contactDisplayName,
  contactProfileLinkAccessibleName,
  contactRowAccessibleName,
} from "../../model/contact-accessibility";
import type { AccountTableDensity } from "../../model/account-table-view";
import { formatConfidence, formatToken } from "../../model/formatting";
import readability from "../../components/account-readability.module.css";
import { LookupEmailButton } from "./lookup-email-button";

const personaColors = {
  blue: "bg-[#e9efff] text-[#1f56d8]",
  cyan: "bg-[#e2f6fa] text-[#007e94]",
  green: "bg-[#eaf3e7] text-[#567644]",
  olive: "bg-[#f0f3cf] text-[#68700b]",
  orange: "bg-[#fff0e3] text-[#a95700]",
  pink: "bg-[#fde6f7] text-[#c10087]",
  red: "bg-[#ffdeda] text-[#dd1c12]",
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
}: {
  accountId: string;
  contact: AccountContactSummary;
  density: AccountTableDensity;
  gridTemplateColumns: string;
}) {
  const confidence = formatConfidence(contact.roleOnCommittee.confidence);
  const displayName = contactDisplayName(contact.name);

  return (
    <div
      aria-label={contactRowAccessibleName(contact.name)}
      className={`${readability.uiRegular} ${readability.densityTransition} ${densityHeightClasses[density]} group isolate grid border-b-[0.5px] border-[var(--clue-border-table)] hover:bg-[var(--clue-background-page)]`}
      role="row"
      style={{ gridTemplateColumns }}
    >
      <div className="sticky left-0 z-30 flex items-center justify-center border-r-[0.5px] border-[var(--clue-border-table)] bg-white group-hover:bg-[var(--clue-background-page)]">
        <input
          aria-label={`Select ${contact.name ?? "unnamed contact"}`}
          className="size-4 appearance-none rounded border-[0.5px] border-[#b5bcc6] checked:border-[#567644] checked:bg-[#567644]"
          type="checkbox"
        />
      </div>
      {/* Every row opens its own contact page. The route is what drives which
          profile is fetched, so the affordance is real on row 1 and row n
          alike — it used to be a button wired to a single featured contact. */}
      <Link
        aria-label={contactProfileLinkAccessibleName(contact.name)}
        className="sticky left-14 z-20 flex min-w-0 items-center gap-2 overflow-hidden border-r-[0.5px] border-[var(--clue-border-table)] bg-white px-4 text-left outline-none group-hover:bg-[var(--clue-background-page)] focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-[#cdd5c4]"
        href={`/accounts/${accountId}/contacts/${contact.id}`}
      >
        <ContactAvatar decorative name={contact.name} size={24} />
        <span className={`${readability.uiMedium} truncate`}>
          {displayName}
        </span>
        <span className="ml-auto opacity-0 transition-opacity group-hover:opacity-100">
          <DesignIcon name="arrow-up-right" size={12} />
        </span>
      </Link>
      <div className="flex items-center border-r-[0.5px] border-[var(--clue-border-table)] px-4">
        {/* A withheld title is absent WITH a marker; a title we simply do not
            hold is absent and unmarked. The wire says which. */}
        {contact.titleRestricted ? (
          <Restricted />
        ) : contact.title ? (
          <span className="truncate">{contact.title}</span>
        ) : (
          <Absent />
        )}
      </div>
      <div className="flex items-center border-r-[0.5px] border-[var(--clue-border-table)] px-4">
        <span
          className={`${readability.pillMedium} rounded-xl px-2 py-1 shadow-[var(--clue-shadow-low)] ${personaColors[contactPersonaTone(contact.persona)]}`}
        >
          {contactPersonaLabel(contact.persona)}
        </span>
      </div>
      <div className="flex items-center gap-1.5 border-r-[0.5px] border-[var(--clue-border-table)] px-4">
        <span className="truncate">
          {formatToken(contact.roleOnCommittee.value)}
        </span>
        {confidence ? (
          <span className="shrink-0 text-[var(--clue-content-subtle)]">
            {confidence}
          </span>
        ) : null}
      </div>
      <div className="flex items-center border-r-[0.5px] border-[var(--clue-border-table)] px-4">
        {/* Signal TYPES, not items: a list-valued facet counts once. */}
        {contact.signals.typeCount > 0 ? (
          <span>
            {contact.signals.typeCount} signal
            {contact.signals.typeCount === 1 ? " type" : " types"}
          </span>
        ) : (
          <Absent label="No signal types" />
        )}
      </div>
      <div className="flex items-center border-r-[0.5px] border-[var(--clue-border-table)] px-4 text-[var(--clue-content-subtle)]">
        <LookupEmailButton />
      </div>
      <div className="flex items-center gap-2 px-4">
        {/* LinkedIn is the only social this surface serves (G2). */}
        {contact.linkedinUrl ? (
          <a
            aria-label={`Open ${contact.name ?? "contact"} on LinkedIn`}
            href={contact.linkedinUrl}
            rel="noreferrer"
            target="_blank"
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              alt="LinkedIn"
              className="size-3 object-contain opacity-80"
              src="/logos/linkedin.svg"
            />
          </a>
        ) : (
          <Absent label="No LinkedIn profile" />
        )}
      </div>
    </div>
  );
}
