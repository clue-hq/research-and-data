import Image from "next/image";
import Link from "./research-link";
import {
  AtSign,
  BookOpen,
  BriefcaseBusiness,
  Building2,
  CalendarClock,
  ChevronDown,
  Gauge,
  Link2,
  Mail,
  MapPin,
  MessageSquareText,
  RadioTower,
  UserRound,
  UsersRound,
  type LucideIcon,
} from "lucide-react";
import type { AccountContactDetail } from "../model/account-contact";
import readability from "./account-readability.module.css";
import components from "./account-components.module.css";
import { ContactAvatar } from "./contact-avatar";
import { ResearchStack, SourceChip } from "./research-content";

const personaToneClasses = {
  blue: components.badgeToneBlue,
  cyan: components.badgeToneCyan,
  green: components.badgeToneGreen,
  olive: components.badgeToneGrass,
  orange: components.badgeToneOrange,
  pink: components.badgeTonePink,
  red: components.badgeToneRed,
} as const;

/** The account glyph shown when the account has no logo asset (ruling S2). */
const ACCOUNT_GLYPH_PATH = "/icons/building.svg";

function ProfileRow({
  icon,
  label,
  children,
}: {
  icon: LucideIcon;
  label: string;
  children: React.ReactNode;
}) {
  const Icon = icon;

  return (
    <div className="flex min-h-8 w-full items-center gap-1">
      <div className={`${readability.fieldLabel} flex w-40 shrink-0 items-center gap-2 text-[var(--clue-content-subtle)]`}>
        <Icon aria-hidden="true" className="size-4 shrink-0" strokeWidth={1.5} />
        <span>{label}</span>
      </div>
      <div className={`${readability.fieldValue} min-w-0 flex-1`}>{children}</div>
    </div>
  );
}

function EvidenceSourceIcon({
  source,
}: {
  source: AccountContactDetail["evidence"][number]["source"];
}) {
  const Icon = source === "link" ? Link2 : AtSign;
  return <Icon aria-hidden="true" className="size-4" strokeWidth={1.5} />;
}

export function ContactIdentity({
  contact,
}: {
  contact: AccountContactDetail;
}) {
  return (
    <div>
      <ContactAvatar name={contact.name} priority size={48} src={contact.avatarUrl} />
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <h1 className={readability.detailTitle}>{contact.name}</h1>
        <span className={`${readability.pillMedium} ${components.badge} ${personaToneClasses[contact.personaTone]}`}>
          {contact.persona}
        </span>
      </div>
    </div>
  );
}

export function ContactDetailsList({
  contact,
}: {
  contact: AccountContactDetail;
}) {
  // The email chip cites the served work-email claim by id (ruling R5); it used
  // to hunt for the address inside evidence text, which cited whatever mentioned it.
  const emailEvidence = contact.emailClaimId
    ? contact.researchEvidence.find(
        (evidence) => evidence.claimId === contact.emailClaimId,
      )
    : undefined;
  return (
    <div>
      <div className="flex flex-col gap-2">
        <h2 className={`${readability.sectionHeading} mb-1 text-[var(--clue-content-subtle)]`}>
          Core
        </h2>
        <ProfileRow icon={UserRound} label="Name">
          {contact.name}
        </ProfileRow>
        <ProfileRow icon={Building2} label="Account">
          <Link
            className="flex w-fit items-center gap-1.5 underline decoration-[var(--clue-content-subtle)] underline-offset-2"
            href={`/accounts/${contact.accountId}`}
          >
            <Image
              alt=""
              aria-hidden="true"
              className="size-3"
              height={12}
              src={contact.accountLogoPath ?? ACCOUNT_GLYPH_PATH}
              unoptimized={contact.accountLogoPath != null}
              width={12}
            />
            {contact.accountName}
          </Link>
        </ProfileRow>
        <ProfileRow icon={BriefcaseBusiness} label={contact.contactDisplay ? "Title" : "Role"}>
          {/* Ruling S7: no title claim renders an em dash, never a guess. */}
          {contact.title ?? "—"}
        </ProfileRow>
        <ProfileRow icon={Gauge} label="Influence">
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
        </ProfileRow>
        <ProfileRow icon={RadioTower} label={contact.contactDisplay ? "Research" : "Recent signals"}>
          <span className={`${readability.pillMedium} ${components.badge} ${components.badgeNeutral}`}>
            {contact.recentSignalsLabel}
          </span>
        </ProfileRow>
        {contact.emailLabel ? (
          <ProfileRow icon={Mail} label="Email">
            <span className="flex flex-wrap items-center gap-1.5">
              <a
                className="underline decoration-[var(--clue-content-subtle)] underline-offset-2"
                href={contact.outreachEligible === false ? undefined : `mailto:${contact.emailLabel}`}
                aria-disabled={contact.outreachEligible === false || undefined}
              >
                {contact.emailLabel}
              </a>
              {emailEvidence ? <SourceChip evidence={emailEvidence} /> : null}
            </span>
          </ProfileRow>
        ) : null}
        <ProfileRow icon={AtSign} label="LinkedIn">
          <a
            className="underline decoration-[var(--clue-content-subtle)] underline-offset-2"
            href={contact.linkedinUrl}
            rel="noreferrer"
            target="_blank"
          >
            {contact.linkedinLabel}
          </a>
        </ProfileRow>
        {contact.xUrl && contact.xLabel ? (
          <ProfileRow icon={AtSign} label="Twitter">
            <a
              className="underline decoration-[var(--clue-content-subtle)] underline-offset-2"
              href={contact.xUrl}
              rel="noreferrer"
              target="_blank"
            >
              {contact.xLabel}
            </a>
          </ProfileRow>
        ) : null}
        {contact.locationLabel ? (
          <ProfileRow icon={MapPin} label="Location">
            {contact.locationLabel}
            {contact.locationClaimId && contact.researchEvidence.find((record) => record.claimId === contact.locationClaimId) ? (
              <SourceChip evidence={contact.researchEvidence.find((record) => record.claimId === contact.locationClaimId)!} />
            ) : null}
          </ProfileRow>
        ) : null}
      </div>

      {contact.contactDisplay &&
      (contact.bestFirstChannelLabel ||
        contact.educationLabel ||
        contact.tenureLabel ||
        contact.reports.length > 0) ? (
        <details className="group mt-2">
          <summary className={`${readability.actionMedium} flex h-8 w-fit cursor-pointer list-none items-center gap-1 rounded-[var(--clue-ds-product-component-button-sm-radius)] px-2 text-[var(--clue-content-subtle)] hover:bg-[var(--clue-background-hover)] hover:text-[var(--clue-content-neutral)] [&::-webkit-details-marker]:hidden`}>
            See all details
            <ChevronDown
              aria-hidden="true"
              className="size-3.5 transition-transform group-open:rotate-180"
              strokeWidth={1.5}
            />
          </summary>
          <div className="mt-2 flex flex-col gap-2">
            {contact.linkedinFollowers !== undefined ? (
              <ProfileRow icon={AtSign} label="LinkedIn profile">
                {contact.linkedinFollowers.toLocaleString("en-US")} followers{contact.linkedinCreator ? " · creator" : ""}
              </ProfileRow>
            ) : null}
            {contact.bestFirstChannelLabel ? (
              <ProfileRow icon={MessageSquareText} label="Best first channel">
                {contact.bestFirstChannelLabel}
              </ProfileRow>
            ) : null}
            {contact.educationLabel ? (
              <ProfileRow icon={BookOpen} label="Education">
                {contact.educationLabel}
              </ProfileRow>
            ) : null}
            {contact.tenureLabel ? (
              <ProfileRow icon={CalendarClock} label={`At ${contact.accountName}`}>
                {contact.tenureLabel}
              </ProfileRow>
            ) : null}
            {contact.reports.length > 0 ? (
              <ProfileRow icon={UsersRound} label="Direct reports">
                <span className="flex flex-wrap gap-x-1">
                  {contact.reports.map((report, index) => (
                    <span key={report.contactId}>
                      {index > 0 ? ", " : ""}
                      <Link
                        className="underline decoration-[var(--clue-content-subtle)] underline-offset-2"
                        href={`/accounts/${report.accountId}/contacts/${report.contactId}`}
                      >
                        {report.name}
                      </Link>
                      {report.title ? ` · ${report.title}` : ""}
                    </span>
                  ))}
                </span>
              </ProfileRow>
            ) : null}
          </div>
        </details>
      ) : null}
    </div>
  );
}

export function ContactProfileContent({
  contact,
  showDetails = true,
}: {
  contact: AccountContactDetail;
  showDetails?: boolean;
}) {
  const researchSections = contact.contactDisplay?.sections;

  return (
    <div>
      <ContactIdentity contact={contact} />
      {showDetails ? (
        <div className="mt-9">
          <ContactDetailsList contact={contact} />
        </div>
      ) : null}

      {researchSections ? (
        <section className="mt-10 pb-12" aria-label="Contact research">
          <ResearchStack
            contactId={contact.id}
            evidence={contact.researchEvidence}
            sections={researchSections}
            name={contact.name}
          />
        </section>
      ) : (
        <>
          <section className="mt-9">
            <h2 className={`${readability.sectionHeading} text-[var(--clue-content-subtle)]`}>
              Overview
            </h2>
            <div className={`${readability.bodyCopy} mt-4 space-y-5`}>
              {contact.overviewParagraphs.map((paragraph) => (
                <p key={paragraph}>{paragraph}</p>
              ))}
            </div>
          </section>

          <section className="mt-9 pb-10">
            <div className="flex items-center justify-between">
              <h2 className={`${readability.sectionHeading} text-[var(--clue-content-subtle)]`}>
                Insight &amp; evidence
              </h2>
              <Link className={readability.actionMedium} href={`/accounts/${contact.accountId}/insights`}>
                See all
              </Link>
            </div>
            <div className="mt-4 space-y-3">
              {contact.evidence.length === 0 ? <p className={readability.bodyCopy}>No insight &amp; evidence information found for {contact.name}.</p> : null}
              {contact.evidence.map((evidence) => (
                <a
                  className={`${readability.uiRegular} grid grid-cols-[16px_minmax(0,1fr)_128px] items-center gap-2`}
                  href={evidence.url}
                  key={evidence.id}
                  rel="noreferrer"
                  target="_blank"
                >
                  <EvidenceSourceIcon source={evidence.source} />
                  <span className={`${readability.uiMedium} truncate`}>{evidence.title}</span>
                  <time className="text-right text-[var(--clue-content-subtle)]">
                    {evidence.dateLabel}
                  </time>
                </a>
              ))}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
