import { useCallback, useEffect, useRef, useState } from "react";
import {
  pollContactEmailLookup,
  startContactEmailLookup,
} from "../../data/contact-email-lookup.repository";
import { ClueApiError } from "../../data/clue-api-error";
import type { ContactEmailLookup } from "../../model/account-contact";

type LookupClientState =
  | { kind: "ready"; lookup: ContactEmailLookup | null }
  | { kind: "requesting"; lookup: ContactEmailLookup | null }
  | { kind: "error"; lookup: ContactEmailLookup | null; message: string };

const POLL_DELAY_MS = 3_000;

export function useEmailLookupController({
  accountId,
  contactId,
  initialLookup,
}: {
  accountId: string;
  contactId: string;
  initialLookup: ContactEmailLookup | null;
}) {
  const [state, setState] = useState<LookupClientState>({
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
    const lookup = state.lookup;
    if (lookup?.state !== "pending") return clearPoll;
    clearPoll();
    timeout.current = window.setTimeout(async () => {
      try {
        const next = await pollContactEmailLookup(
          accountId,
          contactId,
          lookup.lookupId,
        );
        setState({ kind: "ready", lookup: next });
      } catch (error) {
        if (error instanceof ClueApiError && error.status === 401) {
          window.location.assign("/sign-in?reason=session_expired");
          return;
        }
        setState({
          kind: "error",
          lookup,
          message: "Email enrichment is temporarily unavailable",
        });
      }
    }, POLL_DELAY_MS);
    return clearPoll;
  }, [accountId, clearPoll, contactId, state.lookup]);

  const lookup = useCallback(async () => {
    if (state.kind === "requesting") return;
    clearPoll();
    setState({ kind: "requesting", lookup: state.lookup });
    try {
      const next = await startContactEmailLookup(accountId, contactId);
      setState({ kind: "ready", lookup: next });
    } catch (error) {
      if (error instanceof ClueApiError && error.status === 401) {
        window.location.assign("/sign-in?reason=session_expired");
        return;
      }
      setState({
        kind: "error",
        lookup: state.lookup,
        message:
          error instanceof ClueApiError && error.status === 503
            ? "Email enrichment unavailable"
            : "Email lookup failed",
      });
    }
  }, [accountId, clearPoll, contactId, state]);

  return { lookup, state };
}
