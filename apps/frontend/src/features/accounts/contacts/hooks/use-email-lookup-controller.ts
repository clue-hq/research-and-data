import { useCallback, useEffect, useRef, useState } from "react";

export type EmailLookupState = "idle" | "loading" | "complete";

/**
 * Visual-state adapter until the contact enrichment endpoint is connected.
 * Replace the timer with the backend mutation without changing the button.
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
