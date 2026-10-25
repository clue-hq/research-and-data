"use client";

import {
  CrmBrandMark,
  CrmConnectDialogs,
  CrmStatusBadge,
} from "@/features/integrations/components/crm-connect-dialogs";
import { CrmIntegrationDialogs } from "@/features/integrations/components/crm-integration-dialogs";
import { useCrmIntegrationActions } from "@/features/integrations/hooks/use-crm-integration-actions";
import { useCrmSettingsConnect } from "@/features/integrations/hooks/use-crm-settings-connect";
import {
  crmConnectionView,
  crmOverwritesView,
  crmPermissionsView,
  crmResearchView,
} from "@/features/integrations/model/crm-integration-page";
import type { CrmIntegration } from "@/features/integrations/model/crm-settings";
import { crmOverviewCard } from "@/features/integrations/model/crm-settings-overview";
import { CrmConnectionSection } from "./crm-connection-section";
import { CrmOverwritesSection } from "./crm-overwrites-section";
import { CrmPermissionsSection } from "./crm-permissions-section";
import { CrmResearchSection } from "./crm-research-section";
import styles from "./crm-integration-page.module.css";

/**
 * Settings → Integrations → {CRM} (Figma NcLl2r0dzVDN28xAQCwvM1: board 02 HubSpot 2308:1592,
 * board 03 Salesforce 2308:1593, board 07 states, board 06 dialogs). The route renders it only
 * for the connected CRM. `pageWorkspace` is the workspace the page was loaded for.
 */
export function CrmIntegrationPage({
  integration,
  pageWorkspace,
}: {
  integration: CrmIntegration;
  pageWorkspace: string | null;
}) {
  const connect = useCrmSettingsConnect({ pageWorkspace, connection: integration.connection });
  const actions = useCrmIntegrationActions(pageWorkspace);
  const connection = crmConnectionView(integration);
  const accountLine = crmOverviewCard(integration).lines[0]?.text ?? "";
  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <CrmBrandMark provider={connection.provider} size="large" />
        <div className={styles.headerText}>
          <div className={styles.titleRow}>
            <p className={styles.providerName}>{connection.name}</p>
            <CrmStatusBadge tone={connection.badge.tone}>{connection.badge.label}</CrmStatusBadge>
          </div>
          <p className={styles.subtle}>{accountLine}</p>
        </div>
      </div>
      <CrmConnectionSection
        onChange={connect.startChange}
        onDisconnect={actions.openDisconnect}
        onReconnect={() => connect.startReconnect(connection.provider)}
        view={connection}
      />
      <CrmResearchSection view={crmResearchView(integration)} />
      <CrmPermissionsSection onRevoke={actions.openRevoke} view={crmPermissionsView(integration)} />
      <CrmOverwritesSection
        busy={actions.busy}
        error={actions.overwritesError}
        onChoose={actions.chooseOverwrites}
        view={crmOverwritesView(integration)}
      />
      <CrmConnectDialogs {...connect.dialogProps} />
      <CrmIntegrationDialogs
        busy={actions.busy}
        dialog={actions.dialog}
        error={actions.dialogError}
        onCancel={actions.closeDialog}
        onConfirm={actions.confirmDialog}
        permissions={integration.permissions}
        provider={connection.provider}
      />
    </div>
  );
}
