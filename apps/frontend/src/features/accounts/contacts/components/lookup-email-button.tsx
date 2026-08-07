"use client";

import { useEmailLookupController } from "../hooks/use-email-lookup-controller";

const labels = {
  complete: "Email found",
  idle: "Look up",
  loading: "Looking up…",
} as const;

export function LookupEmailButton() {
  const controller = useEmailLookupController();

  return (
    <button
      className="flex h-5 items-center gap-1 rounded-lg text-[12px] leading-4 font-medium text-[var(--clue-content-subtle)] transition-colors hover:bg-[var(--clue-background-hover)] hover:text-[var(--clue-content-neutral)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#cdd5c4]"
      onClick={controller.lookup}
      type="button"
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        alt=""
        aria-hidden="true"
        className="size-3 object-contain"
        src="/icons/contact-email-search.svg"
      />
      <span className="py-0.5">{labels[controller.state]}</span>
    </button>
  );
}
