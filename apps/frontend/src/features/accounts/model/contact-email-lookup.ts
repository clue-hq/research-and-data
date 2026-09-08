import { z } from "zod";

/**
 * The contact email-lookup contract.
 *
 * It lives beside, not inside, `account-contact.ts`: that file is the lifted
 * research/display contract from the design build, while these two schemas are
 * the platform's own mutation contract, consumed by the bulk-action and
 * email-lookup repositories.
 */
export const EmailLookupStateSchema = z.enum([
  "pending",
  "available",
  "not_found",
  "withheld",
  "unavailable",
  "failed",
]);

export const ContactEmailLookupSchema = z.object({
  lookupId: z.string(),
  state: EmailLookupStateSchema,
  // Retained machine metadata; the UI does not add verification/corroboration badges.
  resolution: z.enum([
    "pending",
    "matched",
    "single_source",
    "conflict",
    "none",
    "withheld",
    "unavailable",
    "failed",
  ]),
  emails: z
    .array(
      z.object({
        value: z.string().email(),
        sources: z.array(
          z.object({ key: z.string(), label: z.string() }),
        ),
      }),
    )
    .default([]),
  retryable: z.boolean().default(false),
});

export type EmailLookupState = z.infer<typeof EmailLookupStateSchema>;
export type ContactEmailLookup = z.infer<typeof ContactEmailLookupSchema>;

/** `pending` is the one non-terminal state: everything else ends the poll. */
export function isEmailLookupPending(
  lookup: ContactEmailLookup | null,
): boolean {
  return lookup?.state === "pending";
}

/**
 * The one address a contact row can show, or `null`.
 *
 * A conflict (two sources, two addresses) resolves to `null` on purpose: the
 * row has a single email slot, and silently showing the first would hide the
 * disagreement. The control says so in words instead.
 */
export function resolvedEmailAddress(
  lookup: ContactEmailLookup | null,
): string | null {
  if (!lookup || lookup.state !== "available" || lookup.emails.length !== 1) {
    return null;
  }
  return lookup.emails[0]?.value ?? null;
}

/**
 * Put a resolved address on the contact the row renders.
 *
 * The served contact is never mutated and an unresolved lookup changes nothing,
 * so a row shows a looked-up email exactly when the backend resolved one.
 */
export function applyEmailLookupToContact<
  T extends { emailLabel?: string; emailStatus: "available" | "lookup" },
>(contact: T, lookup: ContactEmailLookup | null): T {
  const address = resolvedEmailAddress(lookup);
  if (!address) return contact;
  return { ...contact, emailLabel: address, emailStatus: "available" };
}

/** What the lookup control is doing, as the design build's button reads it. */
export type EmailLookupControlState =
  | "idle"
  | "loading"
  | "complete"
  | "empty"
  | "error";

export type EmailLookupPhase =
  | { kind: "ready"; lookup: ContactEmailLookup | null }
  | { kind: "requesting"; lookup: ContactEmailLookup | null }
  | { kind: "error"; lookup: ContactEmailLookup | null; message: string };

export interface EmailLookupPresentation {
  /** Whether pressing the control again can do anything. */
  actionable: boolean;
  label: string;
  state: EmailLookupControlState;
}

/**
 * Map one lookup phase onto the control's label and state.
 *
 * Every backend outcome gets its own honest words: a transport failure shows
 * the failure, a withheld or empty result says so rather than looking idle, and
 * only a lookup the backend itself marked retryable offers "Try again".
 */
export function presentEmailLookup(
  phase: EmailLookupPhase,
): EmailLookupPresentation {
  const lookup = phase.lookup;

  // The error phase is checked first: a run that stopped (a transport failure,
  // or the poll ceiling) leaves the last served lookup still saying `pending`,
  // and showing "Looking up…" for it would be a lie.
  if (phase.kind === "error") {
    return {
      actionable: lookup?.retryable === true,
      label: lookup?.retryable ? "Try again" : phase.message,
      state: "error",
    };
  }
  if (phase.kind === "requesting" || isEmailLookupPending(lookup)) {
    return { actionable: false, label: "Looking up…", state: "loading" };
  }
  if (lookup?.state === "available") {
    return {
      actionable: false,
      label: lookup.emails.length > 1 ? "Multiple emails found" : "Email found",
      state: "complete",
    };
  }
  if (lookup?.state === "not_found") {
    return { actionable: false, label: "No email found", state: "empty" };
  }
  if (lookup?.state === "withheld") {
    return { actionable: false, label: "Unavailable", state: "empty" };
  }
  if (lookup?.state === "unavailable" || lookup?.state === "failed") {
    return {
      actionable: lookup.retryable,
      label: lookup.retryable ? "Try again" : "Lookup failed",
      state: "error",
    };
  }
  return { actionable: true, label: "Look up", state: "idle" };
}
