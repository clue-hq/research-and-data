import {
  ContactEmailLookupSchema,
  isEmailLookupPending,
  type ContactEmailLookup,
  type EmailLookupPhase,
} from "../model/contact-email-lookup";
import { ClueApiError } from "./clue-api-error";
import { fetchMutation } from "./frontend-mutation";

export async function startContactEmailLookup(
  accountId: string,
  contactId: string,
): Promise<ContactEmailLookup> {
  const body = await fetchMutation(
    `/accounts/${encodeURIComponent(accountId)}/contacts/${encodeURIComponent(contactId)}/email-lookup`,
    { method: "POST", body: "{}" },
  );
  return ContactEmailLookupSchema.parse(body);
}

export async function pollContactEmailLookup(
  accountId: string,
  contactId: string,
  lookupId: string,
): Promise<ContactEmailLookup> {
  const body = await fetchMutation(
    `/accounts/${encodeURIComponent(accountId)}/contacts/${encodeURIComponent(contactId)}/email-lookup/${encodeURIComponent(lookupId)}/poll`,
    { method: "POST", body: "{}" },
  );
  return ContactEmailLookupSchema.parse(body);
}

/** How long the browser waits between polls of one running lookup. */
export const EMAIL_LOOKUP_POLL_DELAY_MS = 3_000;

/**
 * How many times one lookup is polled before the browser gives up.
 *
 * 40 × 3s ≈ 2 minutes. A lookup the backend never settles must not poll for the
 * lifetime of the page: past the ceiling the control says so and the operator
 * decides whether to ask again.
 */
export const EMAIL_LOOKUP_POLL_LIMIT = 40;

export const EMAIL_LOOKUP_TIMEOUT_MESSAGE =
  "Email lookup is taking longer than expected — try again later";

export type EmailLookupFollowOutcome =
  | "settled"
  | "exhausted"
  | "failed"
  | "session_expired"
  | "cancelled";

const sleep = (ms: number) =>
  new Promise<void>((resolve) => {
    setTimeout(resolve, ms);
  });

/**
 * Poll one running lookup until it settles, fails, or hits the ceiling.
 *
 * Every phase it produces is pushed to `onPhase`, so the caller only holds
 * state. It owns no `window`: an expired session is reported as an outcome for
 * the caller to act on, and cancellation (the row unmounting) is a callback the
 * caller flips, checked before every observable step.
 */
export async function followContactEmailLookup(
  {
    accountId,
    contactId,
    lookupId,
  }: { accountId: string; contactId: string; lookupId: string },
  onPhase: (phase: EmailLookupPhase) => void,
  {
    cancelled = () => false,
    delayMs = EMAIL_LOOKUP_POLL_DELAY_MS,
    limit = EMAIL_LOOKUP_POLL_LIMIT,
    poll = pollContactEmailLookup,
    wait = sleep,
  }: {
    cancelled?: () => boolean;
    delayMs?: number;
    limit?: number;
    poll?: typeof pollContactEmailLookup;
    wait?: (ms: number) => Promise<void>;
  } = {},
): Promise<EmailLookupFollowOutcome> {
  let latest: ContactEmailLookup | null = null;

  for (let attempt = 0; attempt < limit; attempt += 1) {
    await wait(delayMs);
    if (cancelled()) return "cancelled";
    try {
      latest = await poll(accountId, contactId, lookupId);
    } catch (error) {
      if (cancelled()) return "cancelled";
      if (error instanceof ClueApiError && error.status === 401) {
        return "session_expired";
      }
      onPhase({
        kind: "error",
        lookup: latest,
        message: "Email enrichment is temporarily unavailable",
      });
      return "failed";
    }
    if (cancelled()) return "cancelled";
    onPhase({ kind: "ready", lookup: latest });
    if (!isEmailLookupPending(latest)) return "settled";
  }

  onPhase({ kind: "error", lookup: latest, message: EMAIL_LOOKUP_TIMEOUT_MESSAGE });
  return "exhausted";
}
