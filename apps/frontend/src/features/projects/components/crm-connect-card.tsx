"use client";

import Image from "next/image";
import { useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { useCrmCardWatch } from "@/features/integrations/hooks/use-crm-connect";
import {
  CRM_PROVIDER_NAMES,
  CrmConnectError,
  type CrmConnectCardModel,
  type CrmConnectedState,
  type CrmProvider,
} from "@/features/integrations/model/crm";
import styles from "./crm-connect-card.module.css";

/**
 * The CRM connect card (R-3.10; Figma "CRM connection / Chat card", node 2251:5348), drawn
 * from a finished `connect_crm` tool call.
 *
 * Three states, each driven by what really happened: choosing a CRM; authorizing, once a click
 * opened the CRM's login in a new tab; and connected, once the backend reports the connection
 * (the callback tab says so at once, and the card re-reads the connection while it waits). A
 * login that fails returns the card to choosing, with a message naming the CRM. The chat
 * continues by itself when the CRM connects (the server queues a wake turn, and the chat's
 * thread stream shows it), so the connected card has nothing to press.
 *
 * Copy follows the founder's ruling for this release: Clue only reads deals for the sales
 * analysis, so the card never promises to bring accounts or contacts in.
 */

const DESCRIPTION = "Clue reads your deals to work out your real sales numbers.";
const PROVIDER_DATA = "Accounts, contacts & deals";

const PROVIDER_LOGOS: Record<CrmProvider, { src: string; width: number; height: number }> = {
  hubspot: { src: "/icons/crm/hubspot.svg", width: 28, height: 28 },
  salesforce: { src: "/icons/crm/salesforce.svg", width: 28, height: 19.5 },
};

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
  const [authorizing, setAuthorizing] = useState<CrmProvider | null>(null);
  const [opening, setOpening] = useState<CrmProvider | null>(null);
  const [error, setError] = useState<string | null>(null);
  const watch = useCrmCardWatch(card, authorizing);

  const failure = watch.failed
    ? `${CRM_PROVIDER_NAMES[watch.failed]} didn't connect. Try again.`
    : null;
  const authorizingNow = authorizing !== null && failure === null && watch.connected === null;

  async function connect(provider: CrmProvider) {
    setError(null);
    watch.clearFailure();
    setOpening(provider);
    // Open the tab synchronously (inside the click) so pop-up blockers allow it.
    const tab = window.open("about:blank", "_blank");
    try {
      if (!onConnect) throw new CrmConnectError("Connecting is not available here.", "unavailable");
      const url = await onConnect(card.requestId, provider);
      if (tab) tab.location.href = url;
      else window.open(url, "_blank", "noopener");
      setAuthorizing(provider);
    } catch (failed) {
      tab?.close();
      setError(
        failed instanceof CrmConnectError
          ? failed.message
          : `Could not start the ${CRM_PROVIDER_NAMES[provider]} connection. Please try again.`,
      );
    } finally {
      setOpening(null);
    }
  }

  function cancel() {
    setAuthorizing(null);
    watch.clearFailure();
  }

  if (watch.connected) return <ConnectedCard connected={watch.connected} />;

  const title =
    card.mode === "reconnect" ? "Reconnect your CRM" : card.mode === "switch" ? "Switch your CRM" : "Connect your CRM";
  const message = error ?? failure;

  return (
    <section className={styles.card} data-crm-connect-state={authorizingNow ? "authorizing" : "choose"} aria-label={title}>
      <Header title={title} icon="/icons/crm/link.svg" />
      <div className={styles.providers}>
        {card.providers.map((provider, index) => (
          <ProviderRowGroup key={provider} divider={index > 0}>
            <ProviderRow provider={provider} subtitle={PROVIDER_DATA}>
              {authorizingNow && authorizing === provider ? (
                <Button size="md" variant="primary" disabled>
                  Connecting…
                </Button>
              ) : (
                <Button
                  size="md"
                  variant="primary"
                  disabled={!card.canConnect || !onConnect || opening !== null || authorizingNow}
                  onClick={() => void connect(provider)}
                >
                  Connect
                </Button>
              )}
            </ProviderRow>
          </ProviderRowGroup>
        ))}
      </div>
      <div className={styles.guidance}>
        {message ? (
          <p className={`${styles.caption} ${styles.note} ${styles.alert}`} role="alert">
            {message}
          </p>
        ) : authorizingNow ? (
          <p className={`${styles.caption} ${styles.note}`} role="status">
            <Image alt="" aria-hidden="true" className={styles.spinning} height={14} src="/icons/crm/spinner.svg" width={14} />
            Finish authorization in the window that opened.
          </p>
        ) : (
          <p className={`${styles.caption} ${styles.note}`}>
            <Image alt="" aria-hidden="true" height={14} src="/icons/crm/lock.svg" width={14} />
            {card.canConnect
              ? "You’ll review permissions in your CRM before connecting."
              : "Ask a workspace owner or admin to connect the CRM."}
          </p>
        )}
        <div className={styles.actions}>
          <p className={styles.caption}>
            {authorizingNow ? "You can keep this chat open." : "Connect the CRM your team uses."}
          </p>
          {authorizingNow ? (
            <Button size="md" variant="transparent" onClick={cancel}>
              Cancel
            </Button>
          ) : onSendMessage ? (
            <Button
              size="md"
              variant="transparent"
              disabled={opening !== null}
              onClick={() => onSendMessage("I'll connect the CRM later.")}
            >
              Do this later
            </Button>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function ConnectedCard({ connected }: { connected: CrmConnectedState }) {
  const name = CRM_PROVIDER_NAMES[connected.provider];
  return (
    <section className={styles.card} data-crm-connect-state="connected" aria-label="Your CRM is connected">
      <Header title="Your CRM is connected" icon="/icons/crm/check-header.svg" />
      <div className={styles.providers}>
        <ProviderRow provider={connected.provider} subtitle="Ready to use in this workspace">
          <span className={styles.connectedBadge}>
            <Image alt="" aria-hidden="true" height={14} src="/icons/crm/check-connected-badge.svg" width={14} />
            Connected
          </span>
        </ProviderRow>
      </div>
      <div className={styles.guidance}>
        <p className={`${styles.caption} ${styles.note}`} role="status">
          <Image alt="" aria-hidden="true" height={14} src="/icons/crm/check-guidance.svg" width={14} />
          {name} is connected. Clue carries on in this chat.
        </p>
        <div className={styles.actions}>
          <p className={styles.caption}>{connectedBy(connected)}</p>
        </div>
      </div>
    </section>
  );
}

function Header({ title, icon }: { title: string; icon: string }) {
  return (
    <div className={styles.header}>
      <div className={styles.symbol}>
        <Image alt="" aria-hidden="true" height={20} src={icon} width={20} />
      </div>
      <div className={styles.heading}>
        <h3 className={styles.title}>{title}</h3>
        <p className={styles.description}>{DESCRIPTION}</p>
      </div>
    </div>
  );
}

function ProviderRowGroup({ divider, children }: { divider: boolean; children: ReactNode }) {
  return (
    <>
      {divider ? <div aria-hidden="true" className={styles.divider} /> : null}
      {children}
    </>
  );
}

function ProviderRow({
  provider,
  subtitle,
  children,
}: {
  provider: CrmProvider;
  subtitle: string;
  children: ReactNode;
}) {
  const logo = PROVIDER_LOGOS[provider];
  return (
    <div className={styles.provider}>
      <div className={styles.logo}>
        <Image alt="" aria-hidden="true" height={logo.height} src={logo.src} width={logo.width} />
      </div>
      <div className={styles.providerDetails}>
        <p className={styles.providerName}>{CRM_PROVIDER_NAMES[provider]}</p>
        <p className={styles.caption}>{subtitle}</p>
      </div>
      {children}
    </div>
  );
}

/** "Connected by Aryan · today", "… · yesterday", or "… · 20 Oct". */
function connectedBy(connected: CrmConnectedState): string {
  const when = new Date(connected.connectedAt);
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  const day =
    when.toDateString() === today.toDateString()
      ? "today"
      : when.toDateString() === yesterday.toDateString()
        ? "yesterday"
        : when.toLocaleDateString(undefined, { day: "numeric", month: "short" });
  return connected.connectedByName ? `Connected by ${connected.connectedByName} · ${day}` : `Connected ${day}`;
}
