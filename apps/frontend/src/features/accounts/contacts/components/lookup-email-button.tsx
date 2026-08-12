"use client";

import type { ContactEmailLookup } from "../../model/account-contact";
import { useEmailLookupController } from "../hooks/use-email-lookup-controller";

function LookupControl({
  label,
  onClick,
}: {
  label: string;
  onClick?: () => void;
}) {
  return (
    <button
      className="flex h-5 items-center gap-1 rounded-lg text-[12px] leading-4 font-medium text-[var(--clue-content-subtle)] transition-colors hover:bg-[var(--clue-background-hover)] hover:text-[var(--clue-content-neutral)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#cdd5c4] disabled:cursor-default disabled:hover:bg-transparent"
      disabled={onClick === undefined}
      onClick={onClick}
      type="button"
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        alt=""
        aria-hidden="true"
        className="size-3 object-contain"
        src="/icons/contact-email-search.svg"
      />
      <span className="py-0.5">{label}</span>
    </button>
  );
}

export function LookupEmailButton({
  accountId,
  contactId,
  initialLookup,
}: {
  accountId: string;
  contactId: string;
  initialLookup: ContactEmailLookup | null;
}) {
  const controller = useEmailLookupController({
    accountId,
    contactId,
    initialLookup,
  });
  const lookup = controller.state.lookup;
  const emails = lookup?.emails ?? [];

  if (emails.length > 0) {
    const conflicting = emails.length > 1;
    return (
      <div className="flex min-w-0 flex-col gap-0.5" aria-live="polite">
        {emails.map((email) => (
          <a
            className="truncate text-[var(--clue-content-neutral)] hover:underline"
            href={`mailto:${email.value}`}
            key={email.value}
          >
            {email.value}
            {conflicting ? (
              <span className="ml-1 text-[var(--clue-content-subtle)]">
                ({email.sources.map((source) => source.label).join(", ")})
              </span>
            ) : null}
          </a>
        ))}
        {lookup?.state === "pending" ? (
          <span className="sr-only">Checking the remaining email source</span>
        ) : null}
      </div>
    );
  }

  if (controller.state.kind === "requesting" || lookup?.state === "pending") {
    return <LookupControl label="Looking up…" />;
  }
  if (lookup?.state === "not_found") {
    return <span aria-label="No email found">—</span>;
  }
  if (lookup?.state === "withheld") {
    return <span aria-label="Email withheld">Unavailable</span>;
  }
  if (lookup?.state === "unavailable") {
    return <LookupControl label="Try again" onClick={controller.lookup} />;
  }
  if (controller.state.kind === "error") {
    return (
      <LookupControl
        label={lookup?.retryable ? "Try again" : controller.state.message}
        onClick={lookup?.retryable ? controller.lookup : undefined}
      />
    );
  }
  if (lookup?.state === "failed") {
    return (
      <LookupControl
        label={lookup.retryable ? "Try again" : "Lookup failed"}
        onClick={lookup.retryable ? controller.lookup : undefined}
      />
    );
  }
  return <LookupControl label="Look up" onClick={controller.lookup} />;
}
