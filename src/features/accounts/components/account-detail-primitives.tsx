import Image from "next/image";
import Link from "next/link";
import { SidebarIcon } from "@/components/shell/sidebar-icon";
import type {
  AccountContact,
  AccountDetail,
} from "../model/account-detail";
import readability from "./account-readability.module.css";
import { ContactAvatar } from "./contact-avatar";

export function FitBadge({
  compact = false,
  fit,
  neutral = false,
}: {
  compact?: boolean;
  fit: string;
  neutral?: boolean;
}) {
  const high = fit === "High" && !neutral;

  return (
    <span
      className={`${readability.pillMedium} inline-flex items-center rounded-xl px-2 py-1 shadow-[var(--clue-shadow-low)] ${
        high
          ? "bg-[var(--clue-fit-high-background)] text-[var(--clue-fit-high-content)]"
          : "bg-[var(--clue-background-pressed)] text-[var(--clue-content-neutral)]"
      } ${compact ? "min-h-6" : "min-h-7"}`}
    >
      {fit}
    </span>
  );
}

export function AccountIdentity({ account }: { account: AccountDetail }) {
  return (
    <div className="h-[100px] w-full">
      <div className="flex size-[68px] items-center justify-center rounded-lg border-[0.5px] border-[var(--clue-border-neutral)] bg-white">
        <Image
          alt=""
          aria-hidden="true"
          className="size-9 object-contain"
          height={36}
          priority
          src={account.logoPath}
          width={36}
        />
      </div>
      <h1 className={`${readability.detailTitle} mt-2`}>{account.name}</h1>
    </div>
  );
}

type PropertyIconName =
  | "account"
  | "contacts"
  | "fit"
  | "globe"
  | "hash";

function PropertyIcon({ name }: { name: PropertyIconName }) {
  if (name === "account") {
    return <SidebarIcon name="account" />;
  }

  if (name === "contacts") {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img alt="" className="size-4 object-contain" src="/icons/detail/contacts.png" />
    );
  }

  return (
    <span className="flex size-4 items-center justify-center">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        alt=""
        className="max-h-4 max-w-4 object-contain"
        src={`/icons/detail/${name === "fit" ? "circle-chevron-down" : name}.svg`}
      />
    </span>
  );
}

function DetailsRow({
  children,
  compact = false,
  icon,
  label,
}: {
  children: React.ReactNode;
  compact?: boolean;
  icon: PropertyIconName;
  label: string;
}) {
  return (
    <div
      className={`flex w-full items-center gap-1 ${
        compact ? "min-h-7" : "min-h-8"
      }`}
    >
      <div className={`${readability.fieldLabel} flex w-40 shrink-0 items-center gap-2 text-[var(--clue-content-subtle)]`}>
        <PropertyIcon name={icon} />
        <span>{label}</span>
      </div>
      <div className={`${readability.fieldValue} min-w-0`}>
        {children}
      </div>
    </div>
  );
}

export function ContactsInline({
  contacts,
}: {
  contacts: AccountContact[];
}) {
  return (
    <div className="flex items-center gap-2.5 whitespace-nowrap">
      {contacts.map((contact) => (
        <span className="flex items-center gap-2" key={contact.id}>
          <ContactAvatar
            name={contact.name}
            size={24}
            src={contact.avatarUrl}
          />
          <span>{contact.name}</span>
        </span>
      ))}
      <button className={`${readability.actionMedium} ml-0.5`} type="button">
        See all
      </button>
    </div>
  );
}

export function AccountDetailsList({
  account,
  showContacts = false,
}: {
  account: AccountDetail;
  showContacts?: boolean;
}) {
  return (
    <div className="flex w-full flex-col gap-2">
      <DetailsRow icon="account" label="Account">
        {account.name}
      </DetailsRow>
      <DetailsRow icon="fit" label="Research status">
        <FitBadge fit="Fully enriched" neutral />
      </DetailsRow>
      <DetailsRow icon="globe" label="Website">
        <a href={account.websiteUrl} rel="noreferrer" target="_blank">
          {account.websiteLabel}
        </a>
      </DetailsRow>
      <DetailsRow icon="fit" label="Size">
        <FitBadge fit={account.sizeLabel} neutral />
      </DetailsRow>
      <DetailsRow icon="hash" label="Locations">
        {account.locationsLabel}
      </DetailsRow>
      <DetailsRow icon="fit" label="Revenue">
        <FitBadge fit={account.revenueLabel} neutral />
      </DetailsRow>
      <DetailsRow icon="fit" label="Referral fit">
        <FitBadge fit={account.referralFit} neutral />
      </DetailsRow>
      <DetailsRow icon="fit" label="Direct access fit">
        <FitBadge fit={account.directAccessFit} neutral />
      </DetailsRow>
      <DetailsRow icon="fit" label="Recall fit">
        <FitBadge fit={account.recallFit} neutral />
      </DetailsRow>
      <DetailsRow icon="fit" label="Overall buying fit">
        <FitBadge fit={account.overallFit} />
      </DetailsRow>
      {showContacts ? (
        <DetailsRow compact icon="contacts" label="Contacts">
          <ContactsInline contacts={account.contacts} />
        </DetailsRow>
      ) : null}
    </div>
  );
}

export function AccountTextSection({
  paragraphs,
  title,
}: {
  paragraphs: string[];
  title: string;
}) {
  return (
    <section>
      <h2 className={`${readability.sectionHeading} text-[var(--clue-content-subtle)]`}>
        {title}
      </h2>
      <div className={`${readability.bodyCopy} mt-3 space-y-5`}>
        {paragraphs.map((paragraph) => (
          <p key={paragraph}>{paragraph}</p>
        ))}
      </div>
    </section>
  );
}

export function PreviewToolbar({ account }: { account: AccountDetail }) {
  return (
    <header className="flex h-[var(--clue-ds-product-dimension-header-action-bar-height)] items-center justify-between border-b-[0.5px] border-[var(--clue-border-neutral)] px-6">
      <div className="flex items-center gap-2.5">
        <Link
          aria-label="Close account preview"
          className="flex size-6 items-center justify-center rounded-lg hover:bg-[var(--clue-background-hover)]"
          href="/accounts"
          prefetch={false}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img alt="" className="h-[9px] w-[9px] object-contain" src="/icons/detail/x.svg" />
        </Link>
        <span className={readability.uiMedium}>
          {account.previewTitle}
        </span>
      </div>
      <div className="flex items-center gap-3">
        <Link
          className="flex h-7 items-center gap-1.5 rounded-md px-1.5 text-[var(--clue-content-subtle)] hover:bg-[var(--clue-background-hover)] hover:text-[var(--clue-content-neutral)]"
          href={`/accounts/${account.id}`}
          prefetch={false}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img alt="" className="size-2.5 object-contain" src="/icons/detail/maximize.svg" />
          <span className={readability.actionMedium}>Open as page</span>
        </Link>
        <button
          aria-label="Copy account link"
          className="flex size-[26px] items-center justify-center rounded-md hover:bg-[var(--clue-background-hover)]"
          type="button"
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img alt="" className="h-[12.59px] w-[12.6px] object-contain" src="/icons/detail/link.svg" />
        </button>
        <button
          aria-label="More account actions"
          className="flex size-[26px] items-center justify-center rounded-md hover:bg-[var(--clue-background-hover)]"
          type="button"
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img alt="" className="h-[2.17px] w-[10.33px] object-contain" src="/icons/detail/ellipsis.svg" />
        </button>
      </div>
    </header>
  );
}
