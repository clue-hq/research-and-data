import { ClueApiError } from "@/features/accounts/data/clue-api-error";
import { CrmWorkspaceChangedError } from "../data/crm-settings.repository";

export type CrmSettingsActionOutcome = { ok: true } | { ok: false; message: string | null };

/**
 * One provider-page action (disconnect, revoke, overwrites): on success the server data is
 * refreshed (the route then redirects a disconnected CRM back to the overview); a workspace
 * switched in another tab reloads the page with no message; any other refusal becomes the one
 * plain sentence shown next to the action.
 */
export async function runCrmSettingsAction(
  deps: { refresh: () => void; reload: () => void },
  action: () => Promise<unknown>,
): Promise<CrmSettingsActionOutcome> {
  try {
    await action();
  } catch (error) {
    if (error instanceof CrmWorkspaceChangedError) {
      deps.reload();
      return { ok: false, message: null };
    }
    return { ok: false, message: crmSettingsActionMessage(error) };
  }
  deps.refresh();
  return { ok: true };
}

export function crmSettingsActionMessage(error: unknown): string {
  if (error instanceof ClueApiError) {
    if (error.status === 403 || error.code === "PERMISSION_REQUIRED") {
      return "Only a workspace owner or admin can change this.";
    }
    if (error.code === "crm_not_connected") {
      return "The CRM is no longer connected. Reload the page to see its current state.";
    }
    if (error.code === "crm_permission_not_found") {
      return "This permission no longer exists. Reload the page to see the current list.";
    }
  }
  return "Something went wrong. Please try again.";
}
