"use client";

import { useCrmCallback } from "../hooks/use-crm-connect";
import { CRM_PROVIDER_NAMES } from "../model/crm";
import styles from "./crm-callback.module.css";

/**
 * Where Composio returns the browser after the CRM's consent screen (R-3.10).
 *
 * It reports the result to the backend once; the backend verifies the connection and wakes the
 * chat that showed the connect card (or Settings refreshes itself), so this tab only has to say
 * what happened. The copy does not know which one started it.
 */
export function CrmCallback({
  requestId,
  status,
  connectedAccountId,
}: {
  requestId: string | null;
  status: string | null;
  connectedAccountId: string | null;
}) {
  const result = useCrmCallback(requestId, status, connectedAccountId);

  const [title, body] =
    result === null
      ? ["Finishing the connection…", "One moment."]
      : result.outcome === "connected"
        ? [
            `${result.provider ? CRM_PROVIDER_NAMES[result.provider] : "Your CRM"} is connected`,
            "You can close this tab. Clue carries on where you started.",
          ]
        : result.outcome === "stale"
          ? [
              "This login is out of date",
              "A newer connect attempt replaced it, or the CRM is already connected. Close this tab and check where you started.",
            ]
          : [
              "That didn't work",
              "Close this tab and try again where you started.",
            ];

  return (
    <main className={styles.page}>
      <section className={styles.card} aria-live="polite">
        <h1 className={styles.title}>{title}</h1>
        <p className={styles.body}>{body}</p>
      </section>
    </main>
  );
}
