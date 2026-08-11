import Link from "next/link";
import { SidebarIcon } from "@/components/shell/sidebar-icon";
import type { AccountDetail, CommitteeMember } from "../model/account-detail";
import { contactPersonaLabel } from "../model/account-contact";
import { formatFieldKeyLabel, formatToken } from "../model/formatting";
import { prosePresentation, type ProseRead } from "../model/prose";
import readability from "./account-readability.module.css";
import { AccountAvatar } from "./account-avatar";
import { Absent, FactList, FactValue } from "./account-facts";
import { ContactAvatar } from "./contact-avatar";

/** A neutral pill for a semantic token the frontend has already formatted. */
export function TokenBadge({
  children,
  compact = false,
}: {
  children: React.ReactNode;
  compact?: boolean;
}) {
  return (
    <span
      className={`${readability.pillMedium} inline-flex items-center rounded-xl bg-[var(--clue-background-pressed)] px-2 py-1 text-[var(--clue-content-neutral)] shadow-[var(--clue-shadow-low)] ${
        compact ? "min-h-6" : "min-h-7"
      }`}
    >
      {children}
    </span>
  );
}

export function AccountIdentity({ account }: { account: AccountDetail }) {
  return (
    <div className="w-full">
      <div className="flex size-[68px] items-center justify-center rounded-lg border-[0.5px] border-[var(--clue-border-neutral)] bg-white">
        {/* The detail wire carries no logo field at all; the list row's
            `logoUrl` is the (still null) one. Initials are the rendering. */}
        <AccountAvatar name={account.name} rounded="lg" size={36} />
      </div>
      <h1 className={`${readability.detailTitle} mt-2`}>{account.name}</h1>
      {account.domain ? (
        <a
          className={`${readability.uiRegular} text-[var(--clue-content-subtle)]`}
          href={`https://${account.domain}`}
          rel="noreferrer"
          target="_blank"
        >
          {account.domain}
        </a>
      ) : null}
      {account.redirectedFrom ? (
        <p
          className={`${readability.uiRegular} mt-2 text-[var(--clue-content-subtle)]`}
        >
          This account was merged. You followed a link to a record that now
          resolves here.
        </p>
      ) : null}
    </div>
  );
}

type PropertyIconName = "account" | "contacts" | "fit" | "globe" | "hash";

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
      className={`flex w-full items-start gap-1 ${
        compact ? "min-h-7" : "min-h-8"
      }`}
    >
      <div className={`${readability.fieldLabel} flex w-40 shrink-0 items-center gap-2 pt-1.5 text-[var(--clue-content-subtle)]`}>
        <PropertyIcon name={icon} />
        <span>{label}</span>
      </div>
      <div className={`${readability.fieldValue} min-w-0 pt-1`}>{children}</div>
    </div>
  );
}

export function CommitteeInline({
  accountId,
  committee,
}: {
  accountId: string;
  committee: CommitteeMember[];
}) {
  if (!committee.length) return <Absent label="No committee resolved yet" />;

  return (
    <div className="flex flex-wrap items-center gap-2.5">
      {committee.map((member) => (
        <span className="flex items-center gap-2" key={member.contactId}>
          <ContactAvatar decorative name={member.name} size={24} />
          <span>{member.name ?? "Unnamed contact"}</span>
        </span>
      ))}
      <Link
        className={`${readability.actionMedium} ml-0.5`}
        href={`/accounts/${accountId}/contacts`}
      >
        See all
      </Link>
    </div>
  );
}

/**
 * The account details rail.
 *
 * Identity comes from the entity row; everything else is the registry-driven
 * `neutralFacts` list, rendered generically off `fieldKey`. There is no
 * research-status row: status is an `(account, project)` fact served on the
 * list, and a detail badge would have to invent one.
 */
export function AccountDetailsList({
  account,
  showCommittee = false,
}: {
  account: AccountDetail;
  showCommittee?: boolean;
}) {
  return (
    <div className="flex w-full flex-col gap-2">
      <DetailsRow icon="account" label="Account">
        {account.name}
      </DetailsRow>
      <DetailsRow icon="globe" label="Domain">
        {account.domain ? (
          <a
            href={`https://${account.domain}`}
            rel="noreferrer"
            target="_blank"
          >
            {account.domain}
          </a>
        ) : (
          <Absent />
        )}
      </DetailsRow>
      <DetailsRow icon="account" label="Also known as">
        {account.aliases.length ? account.aliases.join(", ") : <Absent />}
      </DetailsRow>
      <DetailsRow icon="hash" label="Registry ids">
        {Object.keys(account.registryIds).length ? (
          <span className="flex flex-col gap-0.5">
            {Object.entries(account.registryIds).map(([registry, value]) => (
              <span key={registry}>
                <span className="text-[var(--clue-content-subtle)]">
                  {formatToken(registry)}:
                </span>{" "}
                <FactValue value={value} />
              </span>
            ))}
          </span>
        ) : (
          <Absent />
        )}
      </DetailsRow>
      <DetailsRow icon="globe" label="Headquarters">
        {account.hqGeo ? (
          Object.values(account.hqGeo)
            .filter((part): part is string => typeof part === "string")
            .join(", ") || <Absent />
        ) : (
          <Absent />
        )}
      </DetailsRow>

      <div className="mt-3">
        <h3
          className={`${readability.fieldLabel} mb-2 text-[var(--clue-content-subtle)]`}
        >
          Researched fields
        </h3>
        <FactList facts={account.neutralFacts} />
      </div>

      {showCommittee ? (
        <DetailsRow compact icon="contacts" label="Committee">
          <CommitteeInline
            accountId={account.id}
            committee={account.committee}
          />
        </DetailsRow>
      ) : null}
    </div>
  );
}

/**
 * Coverage, stated for what it is.
 *
 * `researchedFieldCount` counts fields holding a value from ANY writer and has
 * no denominator, so it is never rendered as progress or as a completion
 * meter. `unresolvedFields` is the honest, registry-described research-side
 * companion; the key-only list remains a compatibility fallback.
 */
export function AccountCoveragePanel({ account }: { account: AccountDetail }) {
  const unresolvedFields = account.coverage.unresolvedFields.length
    ? account.coverage.unresolvedFields
    : account.coverage.unresolvedFieldKeys.map((fieldKey) => ({
        description: null,
        fieldKey,
      }));

  return (
    <section>
      <h2
        className={`${readability.sectionHeading} text-[var(--clue-content-subtle)]`}
      >
        Coverage
      </h2>
      <p className={`${readability.uiRegular} mt-2`}>
        {account.coverage.researchedFieldCount} field
        {account.coverage.researchedFieldCount === 1 ? "" : "s"} hold a value
        for this account.
      </p>
      {unresolvedFields.length ? (
        <div className="mt-2">
          <p
            className={`${readability.uiRegular} text-[var(--clue-content-subtle)]`}
          >
            Research asked for these and could not answer them:
          </p>
          <ul className="mt-2 space-y-2">
            {unresolvedFields.map((field) => (
              <li key={field.fieldKey} title={field.fieldKey}>
                <span className={readability.uiMedium}>
                  {formatFieldKeyLabel(field.fieldKey)}
                </span>
                <p
                  className={`${readability.fieldLabel} text-[var(--clue-content-subtle)]`}
                >
                  {field.description ??
                    `Research could not determine ${formatFieldKeyLabel(field.fieldKey).toLocaleLowerCase()}.`}
                </p>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

/**
 * A prose section.
 *
 * The state comes from the live Lane-E prose claim, never from the presence of
 * adjacent facts or a guessed research-completion state.
 */
export function AccountTextSection({
  emptyNote,
  prose,
  restrictedNote,
  title,
}: {
  emptyNote: string;
  prose: ProseRead;
  restrictedNote: string;
  title: string;
}) {
  const presentation = prosePresentation(prose, {
    empty: emptyNote,
    restricted: restrictedNote,
  });

  return (
    <section>
      <h2 className={`${readability.sectionHeading} text-[var(--clue-content-subtle)]`}>
        {title}
      </h2>
      {presentation.kind === "paragraphs" ? (
        <div className={`${readability.bodyCopy} mt-3 space-y-5`}>
          {presentation.paragraphs.map((paragraph) => (
            <p key={paragraph}>{paragraph}</p>
          ))}
        </div>
      ) : (
        <p
          className={`${readability.uiRegular} mt-3 text-[var(--clue-content-subtle)]`}
        >
          {presentation.message}
        </p>
      )}
    </section>
  );
}

/** Persona label for a committee member, formatted frontend-side. */
export function personaBadgeLabel(member: CommitteeMember) {
  return member.roleOnCommittee
    ? formatToken(member.roleOnCommittee)
    : contactPersonaLabel(member.persona);
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
        <span className={readability.uiMedium}>{account.name}</span>
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
