import { useCallback, useEffect, useRef, useState } from "react";
import {
  followContactEmailLookup,
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

/**
 * The real single-contact email lookup: start, then poll until terminal.
 *
 * `POST …/email-lookup` opens the lookup and `followContactEmailLookup` drives
 * `POST …/email-lookup/{id}/poll` while the served lookup says `pending`, up to
 * a fixed ceiling. Nothing is invented on failure — the honest outcome is what
 * the control shows, and an expired session leaves for sign-in instead of
 * rendering as a lookup error.
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
  const requesting = useRef(false);

  // Only the lookup's identity starts a poll run; the run itself owns every
  // phase it produces, so a poll result must not re-enter this effect.
  const pendingLookupId = isEmailLookupPending(phase.lookup)
    ? (phase.lookup?.lookupId ?? null)
    : null;

  useEffect(() => {
    if (!pendingLookupId) return;
    let cancelled = false;
    void followContactEmailLookup(
      { accountId, contactId, lookupId: pendingLookupId },
      (next) => {
        if (!cancelled) setPhase(next);
      },
      { cancelled: () => cancelled },
    ).then((outcome) => {
      if (outcome === "session_expired" && !cancelled) {
        window.location.assign("/sign-in?reason=session_expired");
      }
    });
    return () => {
      cancelled = true;
    };
  }, [accountId, contactId, pendingLookupId]);

  const lookup = useCallback(async () => {
    if (requesting.current) return;
    requesting.current = true;
    setPhase((current) => ({ kind: "requesting", lookup: current.lookup }));
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
      setPhase((current) => ({
        kind: "error",
        lookup: current.lookup,
        message:
          error instanceof ClueApiError && error.status === 503
            ? "Email enrichment unavailable"
            : "Email lookup failed",
      }));
    } finally {
      requesting.current = false;
    }
  }, [accountId, contactId]);

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
