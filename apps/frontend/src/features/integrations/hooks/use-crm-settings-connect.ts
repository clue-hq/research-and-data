"use client";

import { useRouter } from "next/navigation";
import { useCallback, useMemo, useReducer, useRef, useState } from "react";
import { requestConnectLink } from "../data/crm.repository";
import { httpCrmSettingsRepository } from "../data/crm-settings.repository";
import { crmSettingsConnectHandlers, settingsSignIn } from "./crm-sign-in";
import type { CrmProvider } from "../model/crm";
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
  // Each click and each cancel bumps this; a click whose number is stale was cancelled.
  const attempt = useRef(0);

  const onSignIn = useCallback(
    (mode: CrmConnectMode, provider: CrmProvider, requestId: string | null) => {
      const mine = ++attempt.current;
      setBusy(true);
      // Called inside the click: settingsSignIn opens the window before it awaits anything.
      void settingsSignIn(
        {
          requestConnect: (requestMode) => repository.requestConnect(requestMode),
          requestLink: (id, crm) => requestConnectLink(id, crm, fetch, pageWorkspace),
          cancelled: () => attempt.current !== mine,
          dispatch,
          reload: () => window.location.reload(),
        },
        mode,
        provider,
        requestId,
      ).finally(() => setBusy(false));
    },
    [pageWorkspace, repository],
  );

  const { onConnected, onFailed } = useMemo(
    () => crmSettingsConnectHandlers(dispatch, () => router.refresh()),
    [router],
  );
  const onCancel = useCallback(() => {
    attempt.current += 1;
    dispatch({ type: "cancel" });
  }, []);
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
