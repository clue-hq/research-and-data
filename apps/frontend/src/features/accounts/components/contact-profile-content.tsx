import type { AccountContactDetail } from "../model/account-contact";
import { contactPersonaLabel } from "../model/account-contact";
import { contactDisplayName } from "../model/contact-accessibility";
import {
  formatConfidence,
  formatIsoDate,
  formatSemanticToken,
  formatToken,
} from "../model/formatting";
import {
  AccountFlowIcon,
  type AccountFlowIconName,
} from "./account-flow-icon";
import { Absent, FactList, Restricted } from "./account-facts";
import readability from "./account-readability.module.css";
import { ContactAvatar } from "./contact-avatar";
import { AccountTextSection } from "./account-detail-primitives";

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

export function ContactProfileContent({
  contact,
}: {
  contact: AccountContactDetail;
}) {
  const confidence = formatConfidence(contact.roleOnCommittee.confidence);

  return (
    <div>
      <div className="flex items-center gap-3">
        <ContactAvatar decorative name={contact.name} priority size={48} />
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <h1 className={readability.detailTitle}>
          {contactDisplayName(contact.name)}
        </h1>
        <span className={`${readability.pillMedium} rounded-xl bg-[#f0f3cf] px-2 py-1 shadow-[var(--clue-shadow-low)]`}>
          {contactPersonaLabel(contact.persona)}
        </span>
      </div>
      {contact.redirectedFrom ? (
        <p
          className={`${readability.uiRegular} mt-2 text-[var(--clue-content-subtle)]`}
        >
          This contact was merged; you followed a link to a record that now
          resolves here.
        </p>
      ) : null}

      <div className="mt-9">
        <ProfileRow icon="contacts" label="Name">
          {contact.name ?? <Absent />}
        </ProfileRow>
        <ProfileRow icon="account" label="Account">
          {contact.accountName ?? <Absent />}
        </ProfileRow>
        <ProfileRow icon="role" label="Title">
          {contact.titleRestricted ? (
            <Restricted />
          ) : (
            contact.title ?? <Absent />
          )}
        </ProfileRow>
        <ProfileRow icon="influence" label="Committee role">
          <span className="flex items-center gap-2">
            {formatSemanticToken(contact.roleOnCommittee.value)}
            {confidence ? (
              <span className="text-[var(--clue-content-subtle)]">
                {confidence} confidence
              </span>
            ) : null}
          </span>
        </ProfileRow>
        <ProfileRow icon="recent" label="Recent signals">
          {/* Signal TYPES, bounded by a whitelist — never a count of posts. */}
          {contact.signals.typeCount > 0 ? (
            <>
              {contact.signals.typeCount} signal
              {contact.signals.typeCount === 1 ? " type" : " types"}
            </>
          ) : (
            <Absent label="No signal types" />
          )}
        </ProfileRow>
        <ProfileRow icon="linkedin" label="LinkedIn">
          {contact.linkedinUrl ? (
            <a href={contact.linkedinUrl} rel="noreferrer" target="_blank">
              {contact.linkedinUrl.replace(/^https?:\/\/(www\.)?/, "")}
            </a>
          ) : (
            <Absent />
          )}
        </ProfileRow>
        <ProfileRow icon="account" label="Projects">
          {contact.projectIds.length ? (
            `${contact.projectIds.length} project${contact.projectIds.length === 1 ? "" : "s"}`
          ) : (
            <Absent label="Not on any committee yet" />
          )}
        </ProfileRow>
      </div>

      <div className="mt-9">
        <AccountTextSection
          emptyNote="No written contact overview has been composed yet."
          prose={contact.overview}
          restrictedNote="The contact overview is unavailable for display."
          title="Overview"
        />
      </div>

      <section className="mt-9">
        <h2 className={`${readability.sectionHeading} text-[var(--clue-content-subtle)]`}>
          Professional facts
        </h2>
        <div className="mt-4">
          <FactList facts={contact.professionalFacts} />
        </div>
      </section>

      <section className="mt-9 pb-10">
        <h2 className={`${readability.sectionHeading} text-[var(--clue-content-subtle)]`}>
          Evidence
        </h2>
        {/* Non-link provenance chips: evidence URLs stay off this wire (G4). */}
        <div className="mt-4 flex flex-wrap gap-2">
          {contact.evidence.length ? (
            contact.evidence.map((evidence, index) => (
              <span
                className={`${readability.pillMedium} rounded-xl bg-[var(--clue-background-pressed)] px-2 py-1`}
                key={`${evidence.provider}-${index}`}
              >
                {formatToken(evidence.provider)}
                {formatIsoDate(evidence.observedAt)
                  ? ` · ${formatIsoDate(evidence.observedAt)}`
                  : ""}
              </span>
            ))
          ) : (
            <Absent label="No evidence recorded yet" />
          )}
        </div>
      </section>
    </div>
  );
}
