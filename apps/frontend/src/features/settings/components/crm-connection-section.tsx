"use client";

import { Button } from "@/components/ui/button";
import {
  CrmBrandMark,
  CrmStatusBadge,
} from "@/features/integrations/components/crm-connect-dialogs";
import type { CrmConnectionView } from "@/features/integrations/model/crm-integration-page";
import styles from "./crm-integration-page.module.css";

/**
 * The connection section: boards 02/03 "Connection" (2309:1907 / 2309:2283), board 07 "Expired"
 * (2310:2471) and the member view's connection part (2310:2552).
 */
export function CrmConnectionSection({
  view,
  onReconnect,
  onChange,
  onDisconnect,
}: {
  view: CrmConnectionView;
  onReconnect: () => void;
  onChange: () => void;
  onDisconnect: () => void;
}) {
  if (view.expired) {
    return (
      <section className={styles.card} aria-label="Connection">
        <div className={styles.row}>
          <CrmBrandMark provider={view.provider} />
          <div className={styles.titleRow}>
            <p className={styles.providerName}>{view.name}</p>
            <CrmStatusBadge tone={view.badge.tone}>{view.badge.label}</CrmStatusBadge>
          </div>
          <span className={styles.spacer} />
          {view.actions.includes("reconnect") ? (
            <Button onClick={onReconnect} size="design-sm" variant="primary">
              Reconnect
            </Button>
          ) : null}
        </div>
        <p className={styles.warning}>{view.expired.warning}</p>
        <p className={styles.subtle}>{view.expired.note}</p>
        {view.note ? <p className={styles.subtle}>{view.note}</p> : null}
      </section>
    );
  }
  return (
    <section className={styles.card} aria-labelledby="crm-connection-title">
      <h2 className={styles.cardTitle} id="crm-connection-title">
        Connection
      </h2>
      <div className={styles.details}>
        <Detail label={view.accountFieldLabel} value={view.accountLabel} />
        {view.connectedBy ? <Detail label="Connected by" value={view.connectedBy} /> : null}
      </div>
      <div className={styles.divider} />
      {view.actions.length > 0 ? (
        <div className={styles.actions}>
          {view.actions.includes("reconnect") ? (
            <Button onClick={onReconnect} size="design-sm" variant="neutral">
              Reconnect
            </Button>
          ) : null}
          {view.actions.includes("change") ? (
            <Button onClick={onChange} size="design-sm" variant="neutral">
              Change CRM
            </Button>
          ) : null}
          <span className={styles.spacer} />
          {view.actions.includes("disconnect") ? (
            <Button onClick={onDisconnect} size="design-sm" variant="transparent">
              Disconnect
            </Button>
          ) : null}
        </div>
      ) : null}
      {view.note ? <p className={styles.subtle}>{view.note}</p> : null}
    </section>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className={styles.stack}>
      <p className={styles.label}>{label}</p>
      <p className={styles.subtle}>{value}</p>
    </div>
  );
}
