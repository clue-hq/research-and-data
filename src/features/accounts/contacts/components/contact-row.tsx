import Link from "next/link";
import { DesignIcon } from "@/components/ui/design-icon";
import { ContactAvatar } from "../../components/contact-avatar";
import type { AccountContactSummary } from "../../model/account-contact";
import type { AccountTableDensity } from "../../model/account-table-view";
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
  onPreview: () => void;
}) {
  return (
    <div
      className={`${readability.uiRegular} ${readability.densityTransition} ${densityHeightClasses[density]} group isolate grid border-b-[0.5px] border-[var(--clue-border-table)] hover:bg-[var(--clue-background-page)]`}
      role="row"
      style={{ gridTemplateColumns }}
    >
      <div className="sticky left-0 z-30 flex items-center justify-center border-r-[0.5px] border-[var(--clue-border-table)] bg-white group-hover:bg-[var(--clue-background-page)]">
        <input
          aria-label={`Select ${contact.name}`}
          className="size-4 appearance-none rounded border-[0.5px] border-[#b5bcc6] checked:border-[#567644] checked:bg-[#567644]"
          type="checkbox"
        />
      </div>
      <button
        className="sticky left-14 z-20 flex min-w-0 items-center gap-2 overflow-hidden border-r-[0.5px] border-[var(--clue-border-table)] bg-white px-4 text-left outline-none group-hover:bg-[var(--clue-background-page)] focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-[#cdd5c4]"
        onClick={onPreview}
        type="button"
      >
        <ContactAvatar
          name={contact.name}
          size={24}
          src={contact.avatarUrl}
        />
        <span className={`${readability.uiMedium} truncate`}>{contact.name}</span>
        {contact.id === "denise-dresser" ? (
          <span className="ml-auto opacity-0 transition-opacity group-hover:opacity-100">
            <DesignIcon name="arrow-up-right" size={12} />
          </span>
        ) : null}
      </button>
      <div className="flex items-center border-r-[0.5px] border-[var(--clue-border-table)] px-4">
        <span className="truncate">{contact.title}</span>
      </div>
      <div className="flex items-center border-r-[0.5px] border-[var(--clue-border-table)] px-4">
        <span
          className={`${readability.pillMedium} rounded-xl px-2 py-1 shadow-[var(--clue-shadow-low)] ${personaColors[contact.personaTone]}`}
        >
          {contact.persona}
        </span>
      </div>
      <div className="flex items-center border-r-[0.5px] border-[var(--clue-border-table)] px-4">
        <span
          className={`${readability.pillMedium} rounded-xl px-2 py-1 shadow-[var(--clue-shadow-low)] ${
            contact.influence === "High"
              ? "bg-[var(--clue-fit-high-background)] text-[var(--clue-fit-high-content)]"
              : "bg-[#eef1e9] text-[#567644]"
          }`}
        >
          {contact.influence}
        </span>
      </div>
      <div className="flex items-center border-r-[0.5px] border-[var(--clue-border-table)] px-4 text-[var(--clue-content-subtle)]">
        <LookupEmailButton />
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
      {contact.id === "denise-dresser" ? (
        <Link
          className="sr-only"
          href={`/accounts/${accountId}/contacts/${contact.id}`}
        >
          Open {contact.name}
        </Link>
      ) : null}
    </div>
  );
}
