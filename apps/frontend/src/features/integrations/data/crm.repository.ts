import {
  CompleteResponseSchema,
  ConnectLinkResponseSchema,
  CrmConnectError,
  type CompleteResponse,
  type CrmProvider,
} from "../model/crm";

const CRM_PATH = "/api/clue/frontend/v1/crm";

async function errorCode(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: { code?: string } };
    return body.detail?.code ?? `HTTP_${response.status}`;
  } catch {
    return `HTTP_${response.status}`;
  }
}

/** A fresh Composio login link for this connect card (links live about ten minutes). */
export async function requestConnectLink(
  requestId: string,
  provider: CrmProvider,
  clueFetch: typeof fetch = fetch,
): Promise<string> {
  const response = await clueFetch(`${CRM_PATH}/connect-link`, {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ requestId, provider }),
  });
  if (!response.ok) {
    const code = await errorCode(response);
    if (response.status === 403) {
      throw new CrmConnectError("Only a workspace owner or admin can connect the CRM.", code);
    }
    if (code === "connect_request_closed") {
      throw new CrmConnectError(
        "This connect card is no longer open — the CRM may already be connected.",
        code,
      );
    }
    throw new CrmConnectError("Could not start the connection. Please try again.", code);
  }
  return ConnectLinkResponseSchema.parse(await response.json()).redirectUrl;
}

/** Finish the login the callback page returned from. */
export async function completeConnection(
  requestId: string,
  status: string,
  connectedAccountId: string,
  clueFetch: typeof fetch = fetch,
): Promise<CompleteResponse> {
  const response = await clueFetch(`${CRM_PATH}/complete`, {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ requestId, status, connectedAccountId }),
  });
  if (!response.ok) {
    return { outcome: "failed" };
  }
  return CompleteResponseSchema.parse(await response.json());
}
