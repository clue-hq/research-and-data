"use client";

import type { EmailLookupController } from "../hooks/use-email-lookup-controller";
import readability from "../../components/account-readability.module.css";

/**
 * The design build's lookup control, driven by the real lookup.
 *
 * The presentation is unchanged — same height, same icon, same type scale. Only
 * its words come from the backend's own outcome now (`presentEmailLookup`), and
 * a control that cannot do anything (a lookup already running, a withheld or
 * empty result) is disabled rather than inviting a pointless second request.
 */
export function LookupEmailButton({
  controller,
}: {
  controller: EmailLookupController;
}) {
  return (
    <button
      aria-live="polite"
      className={`${readability.uiMedium} flex h-[26px] items-center gap-1 rounded-[var(--clue-ds-product-component-button-sm-radius)] px-1 text-[var(--clue-content-subtle)] transition-colors hover:bg-[var(--clue-background-hover)] hover:text-[var(--clue-content-neutral)] focus-visible:outline-none focus-visible:shadow-[var(--clue-ds-product-component-button-effect-focus-transparent)] disabled:cursor-default disabled:hover:bg-transparent disabled:hover:text-[var(--clue-content-subtle)]`}
      disabled={!controller.actionable}
      onClick={() => void controller.lookup()}
      type="button"
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        alt=""
        aria-hidden="true"
        className="size-3 object-contain"
        src="/icons/contact-email-search.svg"
      />
      <span>{controller.label}</span>
    </button>
  );
}
