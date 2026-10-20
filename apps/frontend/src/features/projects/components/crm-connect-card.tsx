"use client";

import {
  Confirmation,
  ConfirmationAction,
  ConfirmationActions,
  ConfirmationRequest,
  ConfirmationTitle,
} from "@/components/ai-elements/confirmation";
import { useState } from "react";
import {
  CRM_PROVIDER_NAMES,
  CrmConnectError,
  type CrmConnectCardModel,
  type CrmProvider,
} from "@/features/integrations/model/crm";
import { ProjectIcon } from "./project-icon";
import styles from "./project-flow.module.css";

/**
 * The CRM connect card (R-3.10) — drawn from a finished `connect_crm` tool call.
 *
 * Each click asks the backend for a fresh login link and opens it in a new tab; the CRM's
 * consent screen and Composio's callback happen there, and this chat continues by itself once
 * the connection is active. "I'll give the numbers myself" just answers in the chat.
 * Visual polish is a planned follow-up (R-3.9); this reuses the approval card's look.
 */
export function CrmConnectCard({
  card,
  onConnect,
  onSendMessage,
}: {
  card: CrmConnectCardModel;
  /** Returns a fresh login link for this card and CRM. */
  onConnect?: (requestId: string, provider: CrmProvider) => Promise<string>;
  onSendMessage?: (message: string) => void;
}) {
  const [opening, setOpening] = useState<CrmProvider | null>(null);
  const [opened, setOpened] = useState<CrmProvider | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function connect(provider: CrmProvider) {
    setError(null);
    setOpening(provider);
    // Open the tab synchronously (inside the click) so pop-up blockers allow it.
    const tab = window.open("about:blank", "_blank");
    try {
      if (!onConnect) throw new CrmConnectError("Connecting is not available here.", "unavailable");
      const url = await onConnect(card.requestId, provider);
      if (tab) tab.location.href = url;
      else window.open(url, "_blank", "noopener");
      setOpened(provider);
    } catch (failure) {
      tab?.close();
      setError(
        failure instanceof CrmConnectError
          ? failure.message
          : "Could not start the connection. Please try again.",
      );
    } finally {
      setOpening(null);
    }
  }

  const title =
    card.mode === "reconnect" && card.currentProvider
      ? `Reconnect ${CRM_PROVIDER_NAMES[card.currentProvider]}`
      : card.mode === "switch"
        ? "Switch your CRM"
        : "Connect your CRM";

  return (
    <Confirmation
      approval={{ id: card.requestId }}
      className={styles.planApproval}
      data-crm-connect-mode={card.mode}
      state="approval-requested"
    >
      <ConfirmationRequest>
        <ConfirmationTitle className={styles.planApprovalTitle}>
          <ProjectIcon name="link" size={16} />
          {title}
        </ConfirmationTitle>
        <p className={styles.messageText}>
          Clue reads your deals to work out your real sales numbers. It only reads — nothing in
          your CRM is changed.
        </p>
        {!card.canConnect ? (
          <p className={styles.messageText} role="note">
            Ask a workspace owner or admin to connect the CRM.
          </p>
        ) : null}
        {opened ? (
          <p className={styles.messageText} role="status">
            Finish connecting {CRM_PROVIDER_NAMES[opened]} in the new tab. This chat continues by
            itself once you approve.
          </p>
        ) : null}
        {error ? (
          <p className={styles.messageText} role="alert">
            {error}
          </p>
        ) : null}
      </ConfirmationRequest>
      <ConfirmationActions>
        {card.canConnect && onConnect
          ? card.providers.map((provider) => (
              <ConfirmationAction
                disabled={opening !== null}
                key={provider}
                onClick={() => void connect(provider)}
              >
                {opening === provider ? "Opening…" : `Connect ${CRM_PROVIDER_NAMES[provider]}`}
              </ConfirmationAction>
            ))
          : null}
        {onSendMessage ? (
          <ConfirmationAction
            disabled={opening !== null}
            onClick={() => onSendMessage("I'll give the numbers myself.")}
            variant="outline"
          >
            I&apos;ll give the numbers myself
          </ConfirmationAction>
        ) : null}
      </ConfirmationActions>
    </Confirmation>
  );
}
