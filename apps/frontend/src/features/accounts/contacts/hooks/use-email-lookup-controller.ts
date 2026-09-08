import { useCallback, useEffect, useRef, useState } from "react";
import {
  pollContactEmailLookup,
  startContactEmailLookup,
} from "../../data/contact-email-lookup.repository";
import { ClueApiError } from "../../data/clue-api-error";
import {
  isEmailLookupPending,
  presentEmailLookup,
  type ContactEmailLookup,
  type EmailLookupControlState,
  type EmailLookupPhase,
} from "../../model/contact-email-lookup";

/** The design build's control contract, widened by the states the backend has. */
export type EmailLookupState = EmailLookupControlState;

/** How long the browser waits before asking the backend again. */
const POLL_DELAY_MS = 3_000;

/**
 * The real single-contact email lookup: start, then poll until terminal.
 *
 * `POST …/email-lookup` opens the lookup and `POST …/email-lookup/{id}/poll`
 * advances it; the browser polls only while the served lookup says `pending`,
 * and every other state ends it. Nothing is invented on failure — the honest
 * outcome is what the control shows, and an expired session leaves for sign-in
 * instead of rendering as a lookup error.
 */
export function useEmailLookupController({
  accountId,
  contactId,
  initialLookup = null,
}: {
  accountId: string;
  contactId: string;
  initialLookup?: ContactEmailLookup | null;
}) {
  const [phase, setPhase] = useState<EmailLookupPhase>({
    kind: "ready",
    lookup: initialLookup,
  });
  const timeout = useRef<number | null>(null);

  const clearPoll = useCallback(() => {
    if (timeout.current !== null) {
      window.clearTimeout(timeout.current);
      timeout.current = null;
    }
  }, []);

  useEffect(() => {
    const lookup = phase.lookup;
    if (!isEmailLookupPending(lookup) || !lookup) return clearPoll;
    clearPoll();
    timeout.current = window.setTimeout(async () => {
      try {
        setPhase({
          kind: "ready",
          lookup: await pollContactEmailLookup(
            accountId,
            contactId,
            lookup.lookupId,
          ),
        });
      } catch (error) {
        if (error instanceof ClueApiError && error.status === 401) {
          window.location.assign("/sign-in?reason=session_expired");
          return;
        }
        setPhase({
          kind: "error",
          lookup,
          message: "Email enrichment is temporarily unavailable",
        });
      }
    }, POLL_DELAY_MS);
    return clearPoll;
  }, [accountId, clearPoll, contactId, phase.lookup]);

  const lookup = useCallback(async () => {
    if (phase.kind === "requesting") return;
    clearPoll();
    setPhase({ kind: "requesting", lookup: phase.lookup });
    try {
      setPhase({
        kind: "ready",
        lookup: await startContactEmailLookup(accountId, contactId),
      });
    } catch (error) {
      if (error instanceof ClueApiError && error.status === 401) {
        window.location.assign("/sign-in?reason=session_expired");
        return;
      }
      setPhase({
        kind: "error",
        lookup: phase.lookup,
        message:
          error instanceof ClueApiError && error.status === 503
            ? "Email enrichment unavailable"
            : "Email lookup failed",
      });
    }
  }, [accountId, clearPoll, contactId, phase]);

  const presentation = presentEmailLookup(phase);

  return {
    actionable: presentation.actionable,
    label: presentation.label,
    lookup,
    result: phase.lookup,
    state: presentation.state,
  };
}

export type EmailLookupController = ReturnType<typeof useEmailLookupController>;
