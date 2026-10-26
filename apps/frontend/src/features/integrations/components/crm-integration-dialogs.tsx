"use client";

import { Button } from "@/components/ui/button";
import type { CrmIntegrationDialog } from "../hooks/use-crm-integration-actions";
import type { CrmProvider } from "../model/crm";
import {
  CRM_OVERWRITE_CONFIRM_COPY,
  crmDisconnectCopy,
  crmRevokeCopy,
} from "../model/crm-integration-page";
import type { CrmStandingPermission } from "../model/crm-settings";
import { CrmDialog, DialogActions } from "./crm-connect-dialogs";
import styles from "./crm-connect-dialogs.module.css";

/**
 * The provider page's confirmations (Figma NcLl2r0dzVDN28xAQCwvM1, board 06): "Disconnect
 * HubSpot?" 2310:2395, "Allow changes to people’s values?" 2310:2420 and "Revoke this
 * permission?" 2310:2442. A refused action keeps the dialog open with the refusal in it.
 */
export function CrmIntegrationDialogs({
  dialog,
  provider,
  permissions,
  busy,
  error,
  onCancel,
  onConfirm,
}: {
  dialog: CrmIntegrationDialog | null;
  provider: CrmProvider;
  permissions: readonly CrmStandingPermission[];
  busy: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  if (dialog === null) return null;
  const refusal = error ? (
    <p className={styles.warning} role="alert">
      {error}
    </p>
  ) : null;
  switch (dialog.kind) {
    case "disconnect": {
      const copy = crmDisconnectCopy(provider);
      return (
        <CrmDialog busy={busy} onCancel={onCancel} title={copy.title}>
          <p className={styles.subtle}>{copy.description}</p>
          <p className={styles.neutral}>{copy.consequence}</p>
          {refusal}
          <DialogActions>
            <Button disabled={busy} onClick={onCancel} size="design-sm" variant="neutral">
              Keep connected
            </Button>
            <Button disabled={busy} onClick={onConfirm} size="design-sm" variant="critical">
              Disconnect
            </Button>
          </DialogActions>
        </CrmDialog>
      );
    }
    case "overwrites":
      return (
        <CrmDialog busy={busy} onCancel={onCancel} title={CRM_OVERWRITE_CONFIRM_COPY.title}>
          <p className={styles.subtle}>{CRM_OVERWRITE_CONFIRM_COPY.description}</p>
          {refusal}
          <DialogActions>
            <Button disabled={busy} onClick={onCancel} size="design-sm" variant="neutral">
              Cancel
            </Button>
            <Button disabled={busy} onClick={onConfirm} size="design-sm" variant="primary">
              {CRM_OVERWRITE_CONFIRM_COPY.confirm}
            </Button>
          </DialogActions>
        </CrmDialog>
      );
    case "revoke": {
      const permission = permissions.find((grant) => grant.grantId === dialog.grantId);
      if (!permission) return null;
      const copy = crmRevokeCopy(permission);
      return (
        <CrmDialog busy={busy} onCancel={onCancel} title={copy.title}>
          <p className={styles.subtle}>{copy.body}</p>
          {refusal}
          <DialogActions>
            <Button disabled={busy} onClick={onCancel} size="design-sm" variant="neutral">
              Cancel
            </Button>
            <Button disabled={busy} onClick={onConfirm} size="design-sm" variant="primary">
              Revoke permission
            </Button>
          </DialogActions>
        </CrmDialog>
      );
    }
  }
}
