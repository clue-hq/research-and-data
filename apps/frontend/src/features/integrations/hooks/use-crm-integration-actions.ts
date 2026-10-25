"use client";

import { useRouter } from "next/navigation";
import { useCallback, useMemo, useState } from "react";
import { httpCrmSettingsRepository } from "../data/crm-settings.repository";
import type { CrmOverwritesMode } from "../model/crm-settings";
import { runCrmSettingsAction } from "./crm-settings-actions";

/** The provider page's one open confirmation (board 06), or none. */
export type CrmIntegrationDialog =
  | { kind: "disconnect" }
  | { kind: "overwrites" }
  | { kind: "revoke"; grantId: string };

export interface CrmIntegrationActions {
  dialog: CrmIntegrationDialog | null;
  busy: boolean;
  /** The refusal of the dialog's action, shown inside the dialog. */
  dialogError: string | null;
  /** The refusal of an overwrite change made without a dialog ("Always ask me"). */
  overwritesError: string | null;
  openDisconnect: () => void;
  openRevoke: (grantId: string) => void;
  /** "Always ask me" saves at once; Follow “Always allow” asks first (2310:2420). */
  chooseOverwrites: (mode: CrmOverwritesMode) => void;
  closeDialog: () => void;
  confirmDialog: () => void;
}

/**
 * Disconnect, revoke and the overwrite setting on the provider page. Every request names the
 * page's workspace; success refreshes the server data (a disconnected CRM is then redirected back
 * to the overview by the route); a workspace switched in another tab reloads the page.
 */
export function useCrmIntegrationActions(pageWorkspace: string | null): CrmIntegrationActions {
  const router = useRouter();
  const repository = useMemo(() => httpCrmSettingsRepository(pageWorkspace), [pageWorkspace]);
  const [dialog, setDialog] = useState<CrmIntegrationDialog | null>(null);
  const [busy, setBusy] = useState(false);
  const [dialogError, setDialogError] = useState<string | null>(null);
  const [overwritesError, setOverwritesError] = useState<string | null>(null);

  const run = useCallback(
    async (action: () => Promise<unknown>) => {
      setBusy(true);
      try {
        return await runCrmSettingsAction(
          { refresh: () => router.refresh(), reload: () => window.location.reload() },
          action,
        );
      } finally {
        setBusy(false);
      }
    },
    [router],
  );

  const open = useCallback((next: CrmIntegrationDialog) => {
    setDialogError(null);
    setOverwritesError(null);
    setDialog(next);
  }, []);

  const confirmDialog = useCallback(() => {
    if (dialog === null) return;
    const action =
      dialog.kind === "disconnect"
        ? () => repository.disconnect()
        : dialog.kind === "overwrites"
          ? () => repository.setOverwrites("follow_grants")
          : () => repository.revokePermission(dialog.grantId);
    void run(action).then((outcome) => {
      if (outcome.ok) setDialog(null);
      else setDialogError(outcome.message);
    });
  }, [dialog, repository, run]);

  const chooseOverwrites = useCallback(
    (mode: CrmOverwritesMode) => {
      if (mode === "follow_grants") {
        open({ kind: "overwrites" });
        return;
      }
      setOverwritesError(null);
      void run(() => repository.setOverwrites("ask")).then((outcome) => {
        if (!outcome.ok) setOverwritesError(outcome.message);
      });
    },
    [open, repository, run],
  );

  return {
    dialog,
    busy,
    dialogError,
    overwritesError,
    openDisconnect: useCallback(() => open({ kind: "disconnect" }), [open]),
    openRevoke: useCallback((grantId: string) => open({ kind: "revoke", grantId }), [open]),
    chooseOverwrites,
    closeDialog: useCallback(() => {
      if (!busy) setDialog(null);
    }, [busy]),
    confirmDialog,
  };
}
