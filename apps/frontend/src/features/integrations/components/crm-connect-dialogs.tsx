"use client";

import { Dialog } from "@base-ui/react/dialog";
import Image from "next/image";
import { useEffect, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { useCrmConnectionWatch } from "../hooks/use-crm-connect";
import type { CrmConnectDialogsProps } from "../hooks/use-crm-settings-connect";
import type { CrmProvider } from "../model/crm";
import {
  crmChangeCopy,
  crmChooseCopy,
  crmFailureCopy,
  crmFinishCopy,
  crmReconnectCopy,
} from "../model/crm-connect-flow";
import type { CrmConnectMode } from "../model/crm-settings";
import styles from "./crm-connect-dialogs.module.css";

/**
 * Settings → Integrations' connect dialogs (Figma NcLl2r0dzVDN28xAQCwvM1, board 06 2310:2264):
 * "Connect your CRM" 2310:2266, "Finish connecting in HubSpot" 2310:2324, "Reconnect HubSpot"
 * 2310:2347, "Change your CRM?" 2310:2372, and a failed connect after board 07's "Connection
 * action failed" 2310:2489. One modal at a time over the page; the CRM's sign-in opens in a
 * separate window. Driven by `useCrmSettingsConnect`; spread its `dialogProps` here.
 */
export function CrmConnectDialogs(props: CrmConnectDialogsProps) {
  const { flow, connection, busy, onCancel, onContinueChange, onSignIn } = props;
  switch (flow.step) {
    case "closed":
      return null;
    case "choose": {
      const copy = crmChooseCopy();
      return (
        <CrmDialog busy={busy} onCancel={onCancel} title={copy.title}>
          <p className={styles.subtle}>{copy.description}</p>
          {copy.providers.map((row) => (
            <div className={styles.providerRow} key={row.provider}>
              <CrmBrandMark provider={row.provider} />
              <div className={styles.providerText}>
                <p className={styles.providerName}>{row.name}</p>
                <p className={styles.subtle}>{row.subtitle}</p>
              </div>
              <Button
                disabled={busy}
                onClick={() => onSignIn(flow.mode, row.provider, null)}
                size="design-sm"
                variant="neutral"
              >
                Connect
              </Button>
            </div>
          ))}
          <p className={styles.subtle}>{copy.note}</p>
          <DialogActions>
            <CancelButton busy={busy} onCancel={onCancel} />
          </DialogActions>
        </CrmDialog>
      );
    }
    case "confirm_reconnect": {
      const copy = crmReconnectCopy(flow.provider, connection?.accountLabel ?? "");
      return (
        <CrmDialog busy={busy} onCancel={onCancel} title={copy.title}>
          {copy.lines.map((line) => (
            <p className={styles.subtle} key={line}>
              {line}
            </p>
          ))}
          <DialogActions>
            <CancelButton busy={busy} onCancel={onCancel} />
            <Button
              disabled={busy}
              onClick={() => onSignIn("reconnect", flow.provider, null)}
              size="design-sm"
              variant="primary"
            >
              Reconnect
            </Button>
          </DialogActions>
        </CrmDialog>
      );
    }
    case "confirm_change": {
      const copy = crmChangeCopy(connection?.provider ?? "hubspot");
      return (
        <CrmDialog busy={busy} onCancel={onCancel} title={copy.title}>
          <p className={styles.subtle}>{copy.description}</p>
          <p className={styles.neutral}>{copy.consequence}</p>
          <p className={styles.subtle}>{copy.note}</p>
          <DialogActions>
            <CancelButton busy={busy} onCancel={onCancel} />
            <Button onClick={onContinueChange} size="design-sm" variant="primary">
              Continue
            </Button>
          </DialogActions>
        </CrmDialog>
      );
    }
    case "waiting": {
      const copy = crmFinishCopy(flow.provider);
      return (
        <CrmDialog busy={busy} onCancel={onCancel} title={copy.title}>
          <CrmSignInWatch
            key={flow.requestId}
            {...props}
            mode={flow.mode}
            provider={flow.provider}
            requestId={flow.requestId}
          />
          <p className={styles.subtle}>{copy.description}</p>
          <CrmStatusBadge role="status">{copy.status}</CrmStatusBadge>
          <DialogActions>
            <CancelButton busy={false} onCancel={onCancel} />
            <Button
              disabled={busy}
              onClick={() => onSignIn(flow.mode, flow.provider, flow.requestId)}
              size="design-sm"
              variant="neutral"
            >
              Open sign-in again
            </Button>
          </DialogActions>
        </CrmDialog>
      );
    }
    case "failed": {
      const copy = crmFailureCopy(flow.mode, flow.provider, flow.message);
      return (
        <CrmDialog busy={busy} onCancel={onCancel} title={copy.title}>
          <p className={styles.warning} role="alert">
            {copy.message}
          </p>
          {copy.note ? <p className={styles.subtle}>{copy.note}</p> : null}
          <DialogActions>
            <CancelButton busy={busy} onCancel={onCancel} />
            <Button
              disabled={busy}
              onClick={() => onSignIn(flow.mode, flow.provider, flow.requestId)}
              size="design-sm"
              variant="neutral"
            >
              Try again
            </Button>
          </DialogActions>
        </CrmDialog>
      );
    }
  }
}

/** Waits on one request: closes the flow when the connection answers, fails it on the tab's word. */
function CrmSignInWatch({
  before,
  mode,
  provider,
  requestId,
  onConnected,
  onFailed,
}: CrmConnectDialogsProps & { mode: CrmConnectMode; provider: CrmProvider; requestId: string }) {
  const watch = useCrmConnectionWatch(requestId, before, provider);
  useEffect(() => {
    if (watch.connected) onConnected();
  }, [watch.connected, onConnected]);
  useEffect(() => {
    if (watch.failed) onFailed(mode, watch.failed);
  }, [watch.failed, mode, onFailed]);
  return null;
}

function CrmDialog({
  title,
  busy,
  onCancel,
  children,
}: {
  title: string;
  busy: boolean;
  onCancel: () => void;
  children: ReactNode;
}) {
  return (
    <Dialog.Root
      open
      onOpenChange={(open) => {
        if (!open) onCancel();
      }}
    >
      <Dialog.Portal>
        <div className={styles.dialogLayer}>
          <Dialog.Backdrop className={styles.dialogBackdrop} />
          <Dialog.Popup aria-busy={busy} className={styles.dialog}>
            <Dialog.Title className={styles.title} render={<h2 />}>
              {title}
            </Dialog.Title>
            {children}
          </Dialog.Popup>
        </div>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function DialogActions({ children }: { children: ReactNode }) {
  return <div className={styles.actions}>{children}</div>;
}

function CancelButton({ busy, onCancel }: { busy: boolean; onCancel: () => void }) {
  return (
    <Button disabled={busy} onClick={onCancel} size="design-sm" variant="neutral">
      Cancel
    </Button>
  );
}

const BRAND_MARKS: Record<CrmProvider, { src: string; width: number; height: number }> = {
  hubspot: { src: "/icons/crm/hubspot.svg", width: 28, height: 28 },
  salesforce: { src: "/icons/crm/salesforce.svg", width: 28, height: 19.5 },
};

/** A CRM's brand mark at the design's size ("HubSpot / brand mark", "Salesforce / brand mark"). */
export function CrmBrandMark({ provider }: { provider: CrmProvider }) {
  const mark = BRAND_MARKS[provider];
  return (
    <Image
      alt=""
      aria-hidden="true"
      className={styles.brandMark}
      height={mark.height}
      src={mark.src}
      width={mark.width}
    />
  );
}

/** The design's status pill ("Status / Connected", "Status / Waiting for sign-in", "… / Needs attention"). */
export function CrmStatusBadge({
  children,
  tone = "neutral",
  role,
}: {
  children: ReactNode;
  tone?: "neutral" | "warning";
  role?: "status";
}) {
  return (
    <span className={`${styles.badge} ${tone === "warning" ? styles.badgeWarning : ""}`} role={role}>
      {children}
    </span>
  );
}
