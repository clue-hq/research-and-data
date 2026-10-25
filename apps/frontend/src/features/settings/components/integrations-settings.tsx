"use client";

import Link from "next/link";
import { buttonVariants, Button } from "@/components/ui/button";
import {
  CrmBrandMark,
  CrmConnectDialogs,
  CrmStatusBadge,
} from "@/features/integrations/components/crm-connect-dialogs";
import { useCrmSettingsConnect } from "@/features/integrations/hooks/use-crm-settings-connect";
import type { CrmIntegration } from "@/features/integrations/model/crm-settings";
import {
  CRM_OVERVIEW_COPY,
  crmOverviewCard,
  type CrmOverviewCard,
} from "@/features/integrations/model/crm-settings-overview";
import { SectionLead, SettingsCard } from "./settings-primitives";
import styles from "./settings.module.css";

/**
 * Settings → Integrations (Figma NcLl2r0dzVDN28xAQCwvM1: boards 01 2308:1591, 04 2308:1594,
 * 05 2308:1595): the workspace's one CRM card, and the board 06 connect dialogs it opens.
 * `pageWorkspace` is the workspace the page was loaded for; every action names it.
 */
export function IntegrationsSettings({
  integration,
  pageWorkspace,
}: {
  integration: CrmIntegration;
  pageWorkspace: string | null;
}) {
  const connect = useCrmSettingsConnect({ pageWorkspace, connection: integration.connection });
  const card = crmOverviewCard(integration);
  return (
    <div className={styles.sectionStack}>
      <SectionLead>{CRM_OVERVIEW_COPY.heading}</SectionLead>
      <p className={styles.mutedText}>{CRM_OVERVIEW_COPY.description}</p>
      <CrmProviderCard
        card={card}
        onConnect={connect.startConnect}
        onReconnect={() => {
          if (integration.connection) connect.startReconnect(integration.connection.provider);
        }}
      />
      <p className={styles.mutedText}>{CRM_OVERVIEW_COPY.footer}</p>
      <CrmConnectDialogs {...connect.dialogProps} />
    </div>
  );
}

/** The CRM card ("CRM / not-connected" 2309:1732, "CRM / connected" 2309:2636, "CRM / expired" 2309:2790). */
export function CrmProviderCard({
  card,
  onConnect,
  onReconnect,
}: {
  card: CrmOverviewCard;
  onConnect: () => void;
  onReconnect: () => void;
}) {
  return (
    <SettingsCard className={styles.crmCard}>
      <div className={styles.crmCardRow} data-crm-card-state={card.state}>
        <div className={styles.crmLogos}>
          {card.logos.map((provider) => (
            <CrmBrandMark key={provider} provider={provider} />
          ))}
        </div>
        <div className={styles.crmCardText}>
          <div className={styles.crmCardTitle}>
            <p className={styles.connectionName}>{card.title}</p>
            {card.badge ? (
              <CrmStatusBadge tone={card.badge.tone}>{card.badge.label}</CrmStatusBadge>
            ) : null}
          </div>
          {card.lines.map((line) => (
            <p
              className={line.tone === "warning" ? styles.crmWarningText : styles.mutedText}
              key={line.text}
            >
              {line.text}
            </p>
          ))}
        </div>
        {card.actions.length > 0 ? (
          <div className={styles.crmCardActions}>
            {card.actions.map((action) =>
              action === "manage" && card.manageHref ? (
                <Link
                  className={buttonVariants({ size: "design-sm", variant: "neutral" })}
                  href={card.manageHref}
                  key={action}
                  prefetch={false}
                >
                  Manage
                </Link>
              ) : action === "connect" ? (
                <Button key={action} onClick={onConnect} size="design-sm" variant="neutral">
                  Connect
                </Button>
              ) : action === "reconnect" ? (
                <Button key={action} onClick={onReconnect} size="design-sm" variant="neutral">
                  Reconnect
                </Button>
              ) : null,
            )}
          </div>
        ) : null}
      </div>
    </SettingsCard>
  );
}
