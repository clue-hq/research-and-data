"use client";

import { useEmailLookupController } from "../hooks/use-email-lookup-controller";
import readability from "../../components/account-readability.module.css";

const labels = {
  complete: "Email found",
  idle: "Look up",
  loading: "Looking up…",
} as const;

export function LookupEmailButton() {
  const controller = useEmailLookupController();

  return (
    <button
      className={`${readability.uiMedium} flex h-[26px] items-center gap-1 rounded-[var(--clue-ds-product-component-button-sm-radius)] px-1 text-[var(--clue-content-subtle)] transition-colors hover:bg-[var(--clue-background-hover)] hover:text-[var(--clue-content-neutral)] focus-visible:outline-none focus-visible:shadow-[var(--clue-ds-product-component-button-effect-focus-transparent)]`}
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
      <span>{labels[controller.state]}</span>
    </button>
  );
}
