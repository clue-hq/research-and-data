"use client";

import { useRouter } from "next/navigation";
import { useCallback, useMemo, useReducer, useState } from "react";
import { ClueApiError } from "@/features/accounts/data/clue-api-error";
import { WORKSPACE_CHANGED } from "@/features/projects/data/chat-api";
import { requestConnectLink } from "../data/crm.repository";
import {
  CrmWorkspaceChangedError,
  httpCrmSettingsRepository,
} from "../data/crm-settings.repository";
import { CRM_PROVIDER_NAMES, CrmConnectError, type CrmProvider } from "../model/crm";
import {
  CRM_CONNECT_FLOW_CLOSED,
  crmConnectFlowReducer,
  type CrmConnectFlow,
} from "../model/crm-connect-flow";
import type { CrmConnectMode, CrmIntegrationConnection } from "../model/crm-settings";
import type { CrmConnectionBefore } from "./use-crm-connect";

/** Everything `CrmConnectDialogs` needs; spread `dialogProps` onto it. */
export interface CrmConnectDialogsProps {
  flow: CrmConnectFlow;
  /** The connection the page shows; names the CRM and account in the reconnect/change copy. */
  connection: CrmIntegrationConnection | null;
  /** The connection as it was when the flow began; the watch waits for it to change. */
  before: CrmConnectionBefore | null;
  busy: boolean;
  onCancel: () => void;
  onContinueChange: () => void;
  /** Must be called inside the click: it opens the sign-in window synchronously. */
  onSignIn: (mode: CrmConnectMode, provider: CrmProvider, requestId: string | null) => void;
  onConnected: () => void;
  onFailed: (mode: CrmConnectMode, provider: CrmProvider) => void;
}

export interface CrmSettingsConnect {
  flow: CrmConnectFlow;
  startConnect: () => void;
  startReconnect: (provider: CrmProvider) => void;
  startChange: () => void;
  dialogProps: CrmConnectDialogsProps;
}

/**
 * Settings' connect, reconnect and change-CRM flow (board 06) over the chat card's mechanism:
 * a Settings connect request (`POST /crm/connect-request`) → the same Composio login link, opened
 * in a new window → the same callback page and `BroadcastChannel` word → the server data is
 * refreshed once the connection answers. Every request names the page's workspace; a workspace
 * switched in another tab reloads the page, as chats do.
 */
export function useCrmSettingsConnect({
  pageWorkspace,
  connection,
}: {
  pageWorkspace: string | null;
  connection: CrmIntegrationConnection | null;
}): CrmSettingsConnect {
  const router = useRouter();
  const [flow, dispatch] = useReducer(crmConnectFlowReducer, CRM_CONNECT_FLOW_CLOSED);
  const repository = useMemo(() => httpCrmSettingsRepository(pageWorkspace), [pageWorkspace]);
  const [busy, setBusy] = useState(false);

  const onSignIn = useCallback(
    (mode: CrmConnectMode, provider: CrmProvider, requestId: string | null) => {
      // Open the window synchronously (inside the click) so pop-up blockers allow it.
      const tab = window.open("about:blank", "_blank");
      setBusy(true);
      void (async () => {
        try {
          const id = requestId ?? (await repository.requestConnect(mode));
          const url = await requestConnectLink(id, provider, fetch, pageWorkspace);
          if (tab) tab.location.href = url;
          else window.open(url, "_blank", "noopener");
          dispatch({ type: "opened", mode, provider, requestId: id });
        } catch (error) {
          tab?.close();
          if (workspaceChanged(error)) {
            window.location.reload();
            return;
          }
          dispatch({ type: "failed", mode, provider, message: refusalMessage(error, provider) });
        } finally {
          setBusy(false);
        }
      })();
    },
    [pageWorkspace, repository],
  );

  const onConnected = useCallback(() => {
    dispatch({ type: "connected" });
    router.refresh();
  }, [router]);
  const onFailed = useCallback(
    (mode: CrmConnectMode, provider: CrmProvider) =>
      dispatch({
        type: "failed",
        mode,
        provider,
        message: `${CRM_PROVIDER_NAMES[provider]} didn’t connect. Try again.`,
      }),
    [],
  );
  const onCancel = useCallback(() => dispatch({ type: "cancel" }), []);
  const onContinueChange = useCallback(() => dispatch({ type: "continue_change" }), []);
  const before = connection ? { status: connection.status, connectedAt: connection.connectedAt } : null;

  return {
    flow,
    startConnect: useCallback(() => dispatch({ type: "start_connect" }), []),
    startReconnect: useCallback(
      (provider: CrmProvider) => dispatch({ type: "start_reconnect", provider }),
      [],
    ),
    startChange: useCallback(() => dispatch({ type: "start_change" }), []),
    dialogProps: {
      flow,
      connection,
      before,
      busy,
      onCancel,
      onContinueChange,
      onSignIn,
      onConnected,
      onFailed,
    },
  };
}

function workspaceChanged(error: unknown): boolean {
  return (
    error instanceof CrmWorkspaceChangedError ||
    (error instanceof CrmConnectError && error.code === WORKSPACE_CHANGED)
  );
}

function refusalMessage(error: unknown, provider: CrmProvider): string {
  if (error instanceof CrmConnectError) return error.message;
  if (error instanceof ClueApiError && error.status === 403) {
    return "Only a workspace owner or admin can connect the CRM.";
  }
  return `Could not start the ${CRM_PROVIDER_NAMES[provider]} connection. Please try again.`;
}
