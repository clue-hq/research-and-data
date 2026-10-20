"use client";

import { useCrmCallback } from "../hooks/use-crm-connect";
import { CRM_PROVIDER_NAMES } from "../model/crm";
import styles from "./crm-callback.module.css";

/**
 * Where Composio returns the browser after the CRM's consent screen (R-3.10).
 *
 * It reports the result to the backend once; the backend verifies the connection and wakes the
 * chat that showed the connect card, so this tab only has to say what happened.
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
            "You can close this tab. The chat continues by itself.",
          ]
        : result.outcome === "stale"
          ? [
              "This login is out of date",
              "A newer connect attempt replaced it, or the CRM is already connected. Close this tab and check the chat.",
            ]
          : [
              "That didn't work",
              "Close this tab and try again from the chat.",
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
