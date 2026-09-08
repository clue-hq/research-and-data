import { useCallback, useEffect, useRef, useState } from "react";

export type EmailLookupState = "idle" | "loading" | "complete";

/**
 * Visual-state adapter until the contact enrichment endpoint is connected.
 *
 * TODO(D4 Task 5): replace the timer with the real email-lookup POST + poll
 * (`contact-email-lookup.repository.ts`) and update the row from the resolved
 * claim. The button's own contract does not change.
 */
export function useEmailLookupController() {
  const [state, setState] = useState<EmailLookupState>("idle");
  const timeout = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (timeout.current !== null) window.clearTimeout(timeout.current);
    },
    [],
  );

  const lookup = useCallback(() => {
    if (state !== "idle") return;

    setState("loading");
    timeout.current = window.setTimeout(() => setState("complete"), 700);
  }, [state]);

  return { lookup, state };
}
