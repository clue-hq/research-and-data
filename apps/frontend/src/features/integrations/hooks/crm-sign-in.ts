import { ClueApiError } from "@/features/accounts/data/clue-api-error";
import { WORKSPACE_CHANGED } from "@/features/projects/data/chat-api";
import { CRM_PROVIDER_NAMES, CrmConnectError, type CrmProvider } from "../model/crm";
import type { CrmConnectFlowEvent } from "../model/crm-connect-flow";
import type { CrmConnectMode } from "../model/crm-settings";
import { CrmWorkspaceChangedError } from "../data/crm-settings.repository";

/**
 * Open the CRM's sign-in in a new window. The blank window opens synchronously — call this inside
 * the click, before anything awaits — so pop-up blockers allow it; it is navigated once `getUrl`
 * answers, falls back to a fresh window when the blank one was blocked, and is closed when the
 * link fails (the error is rethrown) or when `cancelled()` says the person gave up meanwhile.
 * Shared by the chat's connect card and Settings.
 */
export async function openSignInWindow(
  getUrl: () => Promise<string>,
  {
    open = (...args) => window.open(...args),
    cancelled = () => false,
  }: { open?: typeof window.open; cancelled?: () => boolean } = {},
): Promise<"opened" | "cancelled"> {
  const tab = open("about:blank", "_blank");
  let url: string;
  try {
    url = await getUrl();
  } catch (error) {
    tab?.close();
    throw error;
  }
  if (cancelled()) {
    tab?.close();
    return "cancelled";
  }
  if (tab) tab.location.href = url;
  else open(url, "_blank", "noopener");
  return "opened";
}

export interface SettingsSignInDeps {
  /** `POST /crm/connect-request {mode}` for the page's workspace. */
  requestConnect: (mode: CrmConnectMode) => Promise<string>;
  /** `POST /crm/connect-link` for that request and CRM, naming the page's workspace. */
  requestLink: (requestId: string, provider: CrmProvider) => Promise<string>;
  open?: typeof window.open;
  /** True once the person closed the dialog after this click. */
  cancelled: () => boolean;
  dispatch: (event: CrmConnectFlowEvent) => void;
  reload: () => void;
}

/**
 * One Settings sign-in click: open (or reuse) the Settings connect request, open its login link in
 * a new window, and wait on that request. A workspace switched in another tab reloads the page;
 * a refusal becomes the failed dialog; a cancel while loading starts nothing.
 */
export async function settingsSignIn(
  deps: SettingsSignInDeps,
  mode: CrmConnectMode,
  provider: CrmProvider,
  requestId: string | null,
): Promise<void> {
  let id = requestId;
  try {
    const outcome = await openSignInWindow(
      async () => {
        id ??= await deps.requestConnect(mode);
        return deps.requestLink(id, provider);
      },
      { open: deps.open, cancelled: deps.cancelled },
    );
    if (outcome === "opened" && id !== null) {
      deps.dispatch({ type: "opened", mode, provider, requestId: id });
    }
  } catch (error) {
    if (workspaceChanged(error)) {
      deps.reload();
      return;
    }
    if (deps.cancelled()) return;
    deps.dispatch({ type: "failed", mode, provider, message: settingsRefusalMessage(error, provider) });
  }
}

/** What the connection answering and a failed sign-in do to the Settings flow. */
export function crmSettingsConnectHandlers(
  dispatch: (event: CrmConnectFlowEvent) => void,
  refresh: () => void,
) {
  return {
    onConnected: () => {
      dispatch({ type: "connected" });
      refresh();
    },
    onFailed: (mode: CrmConnectMode, provider: CrmProvider) =>
      dispatch({
        type: "failed",
        mode,
        provider,
        message: `${CRM_PROVIDER_NAMES[provider]} didn’t connect. Try again.`,
      }),
  };
}

function workspaceChanged(error: unknown): boolean {
  return (
    error instanceof CrmWorkspaceChangedError ||
    (error instanceof CrmConnectError && error.code === WORKSPACE_CHANGED)
  );
}

/** Settings' own words for a refused click (the chat card's mention its card). */
function settingsRefusalMessage(error: unknown, provider: CrmProvider): string {
  if (error instanceof CrmConnectError && error.code === "connect_request_closed") {
    return "This connection attempt has ended — the CRM may already be connected. Reload the page to check.";
  }
  if (
    (error instanceof ClueApiError && error.status === 403) ||
    (error instanceof CrmConnectError && error.code === "PERMISSION_REQUIRED")
  ) {
    return "Only a workspace owner or admin can connect the CRM.";
  }
  if (error instanceof CrmConnectError) return error.message;
  return `Could not start the ${CRM_PROVIDER_NAMES[provider]} connection. Please try again.`;
}
