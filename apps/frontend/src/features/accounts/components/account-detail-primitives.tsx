"use client";

import Image from "next/image";
import Link from "./research-link";
import { useState } from "react";
import {
  AtSign,
  BadgeCheck,
  BriefcaseBusiness,
  Building2,
  CalendarDays,
  CalendarPlus,
  ChevronDown,
  ChevronUp,
  CircleDollarSign,
  CircleGauge,
  Clock3,
  Earth,
  Gauge,
  Landmark,
  MapPin,
  SlidersHorizontal,
  UserRound,
  UsersRound,
  Zap,
  type LucideIcon,
} from "lucide-react";
import type { AccountContact, AccountDetail } from "../model/account-detail";
import readability from "./account-readability.module.css";
import components from "./account-components.module.css";
import { ContactAvatar } from "./contact-avatar";
import { FitScoreIndicator } from "./fit-score-indicator";
import { SourceChip } from "./source-chip";
import { useAccountOwner } from "../hooks/use-account-owner";
import { UNASSIGNED_OWNER_LABEL } from "../model/account-owner";

/** The account glyph shown when the account has no logo asset (ruling S2). */
const ACCOUNT_GLYPH_PATH = "/icons/building.svg";

const industryBadgeTones = [
  components.badgeToneOrange,
  components.badgeToneBlue,
  components.badgeToneCyan,
] as const;

const accountDateFormatter = new Intl.DateTimeFormat("en-US", {
  dateStyle: "medium",
  timeZone: "UTC",
});

function formatAccountDate(value?: string) {
  return value ? accountDateFormatter.format(new Date(value)) : "—";
}

export function FitBadge({
  compact = false,
  fit,
  neutral = false,
}: {
  compact?: boolean;
  /** `null` is an unscored account, not a band: it prints an em dash. */
  fit: string | null;
  neutral?: boolean;
}) {
  const high = fit === "High" && !neutral;

  return (
    <span
      className={`${readability.pillMedium} ${components.badge} ${
        high
          ? components.badgePositive
          : components.badgeNeutral
      } ${compact ? "min-h-[26px]" : ""}`}
    >
      {fit ?? "—"}
    </span>
  );
}

export function AccountIdentity({ account }: { account: Pick<AccountDetail, "name" | "logoPath"> }) {
  return (
    <div>
      <div className="flex size-[68px] items-center justify-center rounded-lg border border-[var(--clue-border-neutral)] bg-white">
        <Image
          alt=""
          aria-hidden="true"
          className="size-14 shrink-0 object-contain"
          height={56}
          priority
          src={account.logoPath ?? ACCOUNT_GLYPH_PATH}
          unoptimized={account.logoPath != null}
          width={56}
        />
      </div>
      <h1 className={`${readability.detailTitle} mt-2`}>{account.name}</h1>
    </div>
  );
}

function DetailsRow({
  children,
  compact = false,
  icon: Icon,
  label,
  labelAdornment,
}: {
  children: React.ReactNode;
  compact?: boolean;
  icon: LucideIcon;
  label: string;
  labelAdornment?: React.ReactNode;
}) {
  return (
    <div
      className={`flex w-full items-center gap-1 ${compact ? "min-h-7" : "min-h-8"}`}
    >
      <div className={`${readability.fieldLabel} flex w-40 shrink-0 items-center gap-2 text-[var(--clue-content-subtle)]`}>
        <Icon aria-hidden="true" className="size-4 shrink-0" strokeWidth={1.5} />
        <span className="flex min-w-0 items-center gap-1">
          <span className="truncate" title={label}>{label}</span>
          {labelAdornment}
        </span>
      </div>
      <div className={`${readability.fieldValue} min-w-0 flex-1`}>
        {children}
      </div>
    </div>
  );
}

export function ContactsInline({
  accountId,
  contacts,
}: {
  accountId: string;
  contacts: AccountContact[];
}) {
  return (
    <div className="flex flex-wrap items-center gap-2.5">
      {contacts.slice(0, 3).map((contact) => (
        <Link className="flex items-center gap-2 whitespace-nowrap hover:underline" href={`/accounts/${accountId}/contacts${contact.hasDetail ? `/${contact.id}` : ""}`} key={contact.id}>
          <ContactAvatar
            name={contact.name}
            size={24}
            src={contact.avatarUrl}
          />
          <span>{contact.name}</span>
        </Link>
      ))}
      <Link
        className={`${readability.actionMedium} ml-0.5 rounded-[var(--clue-ds-product-component-button-sm-radius)] px-1.5 py-1 hover:bg-[var(--clue-background-hover)]`}
        href={`/accounts/${accountId}/contacts`}
        prefetch={false}
      >
        See all
      </Link>
    </div>
  );
}

export type AccountDetailsListData = Pick<AccountDetail,
  | "id" | "name" | "owner" | "createdBy" | "industryLabels" | "headcountLabel"
  | "revenueLabel" | "researchStatus" | "researchStatusLabel" | "websiteUrl"
  | "websiteLabel" | "overallFit" | "fitScore" | "fitScoreLabel" | "locationsLabel"
  | "overviewDisplay" | "foundedLabel" | "fundingLabel" | "socials" | "contacts" | "customFields"
> & { createdAt?: string; lastModifiedAt?: string; researchEvidence?: AccountDetail["researchEvidence"] };

export function AccountDetailsList({
  account,
  showContacts = false,
}: {
  account: AccountDetailsListData;
  showContacts?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const owner = useAccountOwner(account);
  const evidenceById = new Map(account.researchEvidence?.map((record) => [record.claimId, record]));
  const primaryCustomFields = account.customFields.filter(
    (field) => field.primary,
  );
  const secondaryCustomFields = account.customFields.filter(
    (field) => !field.primary,
  );

  const renderCustomField = (
    field: AccountDetail["customFields"][number],
  ) => (
    <DetailsRow
      icon={SlidersHorizontal}
      key={field.id}
      label={field.label}
      labelAdornment={
        <Zap
          aria-label="Custom variable"
          className="size-3 shrink-0"
          fill="currentColor"
          strokeWidth={1.25}
        />
      }
    >
      {field.presentation === "score" && Number.isFinite(Number(field.value)) ? (
        <FitScoreIndicator score={Number(field.value)} />
      ) : field.presentation === "badge" ? (
        <FitBadge fit={field.value} neutral={field.value !== "High"} />
      ) : (
        <span className="min-w-0 truncate">{field.value}</span>
      )}
      {field.claimId && evidenceById.has(field.claimId) ? (
        <SourceChip evidence={evidenceById.get(field.claimId)!} />
      ) : null}
    </DetailsRow>
  );

  return (
    <div className="flex w-full flex-col">
      <div className="flex flex-col gap-2">
        <h3 className={`${readability.sectionHeading} mb-1 text-[var(--clue-content-subtle)]`}>
          Core
        </h3>
        <DetailsRow icon={Building2} label="Account">
          {account.name}
        </DetailsRow>
        <DetailsRow icon={UserRound} label="Owner">
            {owner ? (
              <span className="flex min-w-0 items-center gap-2">
                <ContactAvatar
                  name={owner.name}
                  size={22}
                  src={owner.avatarUrl}
                />
                <span className="min-w-0 truncate" title={owner.name}>{owner.name}</span>
              </span>
            ) : (
              <span className="text-[var(--clue-content-disabled)]">{UNASSIGNED_OWNER_LABEL}</span>
            )}
        </DetailsRow>
        <DetailsRow icon={BriefcaseBusiness} label="Industry">
          <div className="flex min-w-0 flex-wrap items-center gap-1.5">
            {account.industryLabels.map((industry, index) => (
              <span
                className={`${readability.pillMedium} ${components.badge} ${industryBadgeTones[index % industryBadgeTones.length]}`}
                key={industry}
              >
                {industry}
              </span>
            ))}
          </div>
        </DetailsRow>
        <DetailsRow icon={UsersRound} label="Headcount">
          <FitBadge fit={account.headcountLabel} neutral />
        </DetailsRow>
        <DetailsRow icon={CircleDollarSign} label="Revenue">
          <FitBadge fit={account.revenueLabel} neutral />
        </DetailsRow>
        <DetailsRow icon={BadgeCheck} label="Research status">
          <FitBadge
            fit={account.researchStatusLabel ?? account.researchStatus}
            neutral
          />
        </DetailsRow>
        <DetailsRow icon={Earth} label="Website">
          {account.websiteUrl ? (
            <a
              className="underline decoration-[var(--clue-content-subtle)] underline-offset-2"
              href={account.websiteUrl}
              rel="noreferrer"
              target="_blank"
            >
              {account.websiteLabel}
            </a>
          ) : (
            <span className="text-[var(--clue-content-disabled)]">{account.websiteLabel}</span>
          )}
        </DetailsRow>
        <DetailsRow icon={Gauge} label="Overall buying fit">
          <FitBadge fit={account.overallFit} />
        </DetailsRow>
        <DetailsRow icon={CircleGauge} label="Fit Score">
          {account.fitScoreLabel ?? (
            <FitScoreIndicator score={account.fitScore} />
          )}
        </DetailsRow>

        {expanded ? (
          <>
            <DetailsRow icon={MapPin} label={account.overviewDisplay ? "HQ" : "Locations"}>
              {account.locationsLabel}
            </DetailsRow>
            {account.foundedLabel ? (
              <DetailsRow icon={CalendarDays} label="Founded">
                {account.foundedLabel}
              </DetailsRow>
            ) : null}
            {account.fundingLabel ? (
              <DetailsRow icon={Landmark} label="Funding">
                {account.fundingLabel}
              </DetailsRow>
            ) : null}
            {account.socials.map((social) => (
              <DetailsRow icon={AtSign} key={social.id} label={social.label}>
                <a
                  className="underline decoration-[var(--clue-content-subtle)] underline-offset-2"
                  href={social.url}
                  rel="noreferrer"
                  target="_blank"
                >
                  {social.label}
                </a>
              </DetailsRow>
            ))}
            <DetailsRow icon={CalendarPlus} label="Date Created">
              {formatAccountDate(account.createdAt)}
            </DetailsRow>
            <DetailsRow icon={Clock3} label="Last Modified">
              {formatAccountDate(account.lastModifiedAt)}
            </DetailsRow>
          </>
        ) : null}
      </div>

      {showContacts ? (
        <div className="mt-5">
          <DetailsRow compact icon={UsersRound} label="Contacts">
            <ContactsInline accountId={account.id} contacts={account.contacts} />
          </DetailsRow>
        </div>
      ) : null}

      {primaryCustomFields.length > 0 ||
      (expanded && secondaryCustomFields.length > 0) ? (
        <div className="mt-5 flex flex-col gap-2">
          <h3 className={`${readability.sectionHeading} mb-1 text-[var(--clue-content-subtle)]`}>
            Custom
          </h3>
          {primaryCustomFields.map(renderCustomField)}
          {expanded ? secondaryCustomFields.map(renderCustomField) : null}
        </div>
      ) : null}

      <button
        aria-expanded={expanded}
        className={`${readability.actionMedium} mt-4 flex h-8 w-fit items-center gap-1 rounded-[var(--clue-ds-product-component-button-sm-radius)] px-2 text-[var(--clue-content-subtle)] transition-colors hover:bg-[var(--clue-background-hover)] hover:text-[var(--clue-content-neutral)]`}
        onClick={() => setExpanded((current) => !current)}
        type="button"
      >
        <span>{expanded ? "Show less" : "See all"}</span>
        {expanded ? (
          <ChevronUp aria-hidden="true" className="size-3.5" strokeWidth={1.5} />
        ) : (
          <ChevronDown aria-hidden="true" className="size-3.5" strokeWidth={1.5} />
        )}
      </button>
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

export function PreviewToolbar({ account, onClose, onNavigateTo }: {
  account: Pick<AccountDetail, "id" | "previewTitle">;
  onClose?: () => void;
  onNavigateTo: (href: string) => void;
}) {
  return (
    <header className="flex h-14 items-center justify-between border-b-[0.5px] border-[var(--clue-border-neutral)] px-6">
      <div className="flex items-center gap-2.5">
        {onClose ? (
          <button aria-label="Close account preview" className={components.iconButton} onClick={onClose} type="button">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img alt="" className="h-[9px] w-[9px] object-contain" src="/icons/detail/x.svg" />
          </button>
        ) : (
          <Link
            aria-label="Close account preview"
            className={components.iconButton}
            href="/accounts"
            prefetch
            onNavigate={(event) => { event.preventDefault(); onNavigateTo("/accounts"); }}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img alt="" className="h-[9px] w-[9px] object-contain" src="/icons/detail/x.svg" />
          </Link>
        )}
        <span className={readability.uiMedium}>
          {account.previewTitle}
        </span>
      </div>
      <div className="flex items-center gap-3">
        <Link
          className={`${readability.actionMedium} flex h-[var(--clue-ds-product-component-button-sm-height)] items-center gap-[var(--clue-ds-product-component-button-gap)] rounded-[var(--clue-ds-product-component-button-sm-radius)] px-[var(--clue-ds-product-component-button-sm-padding-inline)] text-[var(--clue-content-subtle)] hover:bg-[var(--clue-background-hover)] hover:text-[var(--clue-content-neutral)]`}
          href={`/accounts/${account.id}`}
          prefetch
          onNavigate={(event) => { event.preventDefault(); onNavigateTo(`/accounts/${account.id}`); }}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img alt="" className="size-2.5 object-contain" src="/icons/detail/maximize.svg" />
          <span className={readability.actionMedium}>Open as page</span>
        </Link>
        <button
          aria-label="Copy account link"
          className={components.iconButton}
          type="button"
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img alt="" className="h-[12.59px] w-[12.6px] object-contain" src="/icons/detail/link.svg" />
        </button>
        <button
          aria-label="More account actions"
          className={components.iconButton}
          type="button"
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img alt="" className="h-[2.17px] w-[10.33px] object-contain" src="/icons/detail/ellipsis.svg" />
        </button>
      </div>
    </header>
  );
}
