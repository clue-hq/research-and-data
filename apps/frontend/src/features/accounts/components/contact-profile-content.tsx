import Image from "next/image";
import type { AccountContactDetail } from "../model/account-contact";
import {
  AccountFlowIcon,
  type AccountFlowIconName,
} from "./account-flow-icon";
import readability from "./account-readability.module.css";
import { ContactAvatar } from "./contact-avatar";

function ProfileRow({
  icon,
  label,
  children,
}: {
  icon: AccountFlowIconName;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid min-h-10 grid-cols-[148px_minmax(0,1fr)] items-center gap-4">
      <div className={`${readability.fieldLabel} flex items-center gap-2 text-[var(--clue-content-subtle)]`}>
        <span className="flex size-5 shrink-0 items-center justify-center">
          <AccountFlowIcon className="opacity-80" name={icon} size={15} />
        </span>
        <span>{label}</span>
      </div>
      <div className={`${readability.fieldValue} min-w-0`}>{children}</div>
    </div>
  );
}

function EvidenceSourceIcon({
  source,
}: {
  source: AccountContactDetail["evidence"][number]["source"];
}) {
  const src =
    source === "linkedin"
      ? "/logos/linkedin.svg"
      : source === "x"
        ? "/logos/x.svg"
        : "/icons/detail/link.svg";
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img alt="" aria-hidden="true" className="size-4 object-contain" src={src} />
  );
}

export function ContactProfileContent({
  contact,
  compact = false,
}: {
  contact: AccountContactDetail;
  compact?: boolean;
}) {
  return (
    <div className={compact ? "px-16 py-14 max-md:px-6" : ""}>
      <div className="flex items-center gap-3">
        <ContactAvatar
          name={contact.name}
          priority
          size={48}
          src={contact.avatarUrl}
        />
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <h1 className={readability.detailTitle}>{contact.name}</h1>
        <span className={`${readability.pillMedium} rounded-xl bg-[#f0f3cf] px-2 py-1 shadow-[var(--clue-shadow-low)]`}>
          {contact.persona}
        </span>
      </div>

      <div className="mt-9">
        <ProfileRow icon="contacts" label="Name">
          {contact.name}
        </ProfileRow>
        <ProfileRow icon="account" label="Account">
          <span className="flex items-center gap-1.5">
            <Image
              alt=""
              aria-hidden="true"
              className="size-3"
              height={12}
              src={contact.accountLogoPath}
              width={12}
            />
            {contact.accountName}
          </span>
        </ProfileRow>
        <ProfileRow icon="role" label="Role">
          {contact.title}
        </ProfileRow>
        <ProfileRow icon="influence" label="Influence">
          {contact.influence}
        </ProfileRow>
        <ProfileRow icon="recent" label="Recent signals">
          {contact.recentSignalsLabel}
        </ProfileRow>
        <ProfileRow icon="linkedin" label="LinkedIn">
          <a href={contact.linkedinUrl} rel="noreferrer" target="_blank">
            {contact.linkedinLabel}
          </a>
        </ProfileRow>
        <ProfileRow icon="x" label="X">
          <a href={contact.xUrl} rel="noreferrer" target="_blank">
            {contact.xLabel}
          </a>
        </ProfileRow>
      </div>

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
          <button className={readability.actionMedium} type="button">
            See all
          </button>
        </div>
        <div className="mt-4 space-y-3">
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
    </div>
  );
}
