import { readErrorEnvelope } from "@/features/accounts/data/frontend-mutation";
import {
  CompleteResponseSchema,
  ConnectLinkResponseSchema,
  CrmConnectError,
  CrmConnectionResponseSchema,
  type CompleteResponse,
  type CrmConnectionResponse,
  type CrmProvider,
} from "../model/crm";
import { CrmProposalProgressSchema, type CrmProposalProgress } from "../model/crm-write";

const CRM_PATH = "/api/clue/frontend/v1/crm";

/**
 * The refusal's code from the read API's `{error: {code, message, requestId}}` envelope (the
 * frontend-read app rewrites every `HTTPException` into it); `HTTP_<status>` when the body is not
 * that envelope.
 */
export async function crmErrorCode(response: Response): Promise<string> {
  return (await readErrorEnvelope(response))?.code ?? `HTTP_${response.status}`;
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
    const code = await crmErrorCode(response);
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

/** The workspace's CRM connection, as any member may read it. */
export async function fetchCrmConnection(
  clueFetch: typeof fetch = fetch,
): Promise<CrmConnectionResponse> {
  const response = await clueFetch(`${CRM_PATH}/connection`, {
    cache: "no-store",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) throw new Error(`HTTP_${response.status}`);
  return CrmConnectionResponseSchema.parse(await response.json());
}

/** How far a CRM write proposal got (the write permission card after its answer). */
export async function fetchCrmProposal(
  proposalId: string,
  clueFetch: typeof fetch = fetch,
): Promise<CrmProposalProgress> {
  const response = await clueFetch(`${CRM_PATH}/proposals/${encodeURIComponent(proposalId)}`, {
    cache: "no-store",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) throw new Error(await crmErrorCode(response));
  return CrmProposalProgressSchema.parse(await response.json());
}
