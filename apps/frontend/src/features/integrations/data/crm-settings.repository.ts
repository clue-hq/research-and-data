import { ClueApiError } from "@/features/accounts/data/clue-api-error";
import { fetchMutation } from "@/features/accounts/data/frontend-mutation";
import { PAGE_WORKSPACE_HEADER, WORKSPACE_CHANGED } from "@/features/projects/data/chat-api";
import {
  CrmConnectRequestResponseSchema,
  CrmDisconnectResponseSchema,
  CrmIntegrationSchema,
  CrmOverwritesResponseSchema,
  CrmRevokeResponseSchema,
  type CrmConnectMode,
  type CrmIntegration,
  type CrmOverwritesMode,
  type CrmRevokeOutcome,
} from "../model/crm-settings";

/**
 * Settings → Integrations' backend: `GET /crm/integration` and the four Settings actions
 * (contract `docs/api-contracts/crm-settings.md`). Every refusal is a `ClueApiError` carrying the
 * backend's `{error: {code, message, requestId}}` envelope, e.g. `crm_not_connected`,
 * `crm_permission_not_found`, `PERMISSION_REQUIRED`; a workspace switched since the page loaded is
 * a `CrmWorkspaceChangedError`.
 */
export interface CrmSettingsRepository {
  getIntegration(): Promise<CrmIntegration>;
  /** Opens (or reuses) a Settings connect request; its id drives the existing connect flow. */
  requestConnect(mode: CrmConnectMode): Promise<string>;
  disconnect(): Promise<void>;
  revokePermission(grantId: string): Promise<CrmRevokeOutcome>;
  setOverwrites(mode: CrmOverwritesMode): Promise<CrmOverwritesMode>;
}

/**
 * A Settings action refused because the selected workspace changed since the page loaded (the
 * BFF's `409 WORKSPACE_CHANGED`, L4-4). The screen tells the person and reloads; nothing changed.
 */
export class CrmWorkspaceChangedError extends ClueApiError {
  constructor(cause: ClueApiError) {
    super(cause.message, { code: cause.code, status: cause.status, requestId: cause.requestId });
    this.name = "CrmWorkspaceChangedError";
  }
}

/**
 * The browser adapter, through the authenticated `/api/clue` BFF (the shared `fetchMutation`,
 * which reads the `{error: {code, message, requestId}}` envelope into a `ClueApiError`).
 * `pageWorkspace` is the workspace the page was loaded for; every request names it in
 * `X-Clue-Page-Workspace`, so an action never lands on a workspace switched to in another tab.
 */
export function httpCrmSettingsRepository(
  pageWorkspace: string | null,
  clueFetch: typeof fetch = fetch,
): CrmSettingsRepository {
  async function call(path: string, method: string, body?: unknown): Promise<unknown> {
    try {
      return await fetchMutation(
        `/crm${path}`,
        {
          method,
          cache: "no-store",
          headers: pageWorkspace ? { [PAGE_WORKSPACE_HEADER]: pageWorkspace } : {},
          ...(body === undefined ? {} : { body: JSON.stringify(body) }),
        },
        clueFetch,
      );
    } catch (error) {
      if (error instanceof ClueApiError && error.code === WORKSPACE_CHANGED) {
        throw new CrmWorkspaceChangedError(error);
      }
      throw error;
    }
  }

  return {
    async getIntegration() {
      return CrmIntegrationSchema.parse(await call("/integration", "GET"));
    },
    async requestConnect(mode) {
      return CrmConnectRequestResponseSchema.parse(
        await call("/connect-request", "POST", { mode }),
      ).requestId;
    },
    async disconnect() {
      CrmDisconnectResponseSchema.parse(await call("/disconnect", "POST"));
    },
    async revokePermission(grantId) {
      return CrmRevokeResponseSchema.parse(
        await call(`/permissions/${encodeURIComponent(grantId)}/revoke`, "POST"),
      ).outcome;
    },
    async setOverwrites(mode) {
      return CrmOverwritesResponseSchema.parse(await call("/overwrites", "PUT", { mode }))
        .overwrites;
    },
  };
}

function refused(status: number, code: string, message: string): ClueApiError {
  return new ClueApiError(message, { code, status, requestId: null });
}

/**
 * An in-memory adapter over one payload, answering and refusing as the backend does. For design
 * checks and tests (selected explicitly, never as a fallback for a failed live read).
 */
export function fixtureCrmSettingsRepository(initial: CrmIntegration): CrmSettingsRepository {
  let integration = CrmIntegrationSchema.parse(structuredClone(initial));
  const revoked = new Set<string>();

  function manage() {
    if (!integration.canManage) {
      throw refused(403, "PERMISSION_REQUIRED", "This needs workspace.manage_settings.");
    }
  }
  function connected() {
    const connection = integration.connection;
    if (connection === null || connection.status === "disconnected") {
      throw refused(409, "crm_not_connected", "No CRM is connected.");
    }
    return connection;
  }

  return {
    async getIntegration() {
      return structuredClone(integration);
    },
    async requestConnect() {
      manage();
      return crypto.randomUUID();
    },
    async disconnect() {
      manage();
      const connection = connected();
      integration = {
        ...integration,
        connection: { ...connection, status: "disconnected" },
        research: {
          state: "not_connected",
          failedField: null,
          reason: null,
          reviewChat: null,
          items: integration.research.items.map((item) => ({ ...item, status: "pending" })),
        },
        permissions: [],
        overwrites: "ask",
      };
    },
    async revokePermission(grantId) {
      if (revoked.has(grantId)) return "already_revoked";
      if (!integration.permissions.some((grant) => grant.grantId === grantId)) {
        throw refused(404, "crm_permission_not_found", "No such permission here.");
      }
      revoked.add(grantId);
      integration = {
        ...integration,
        permissions: integration.permissions.filter((grant) => grant.grantId !== grantId),
      };
      return "revoked";
    },
    async setOverwrites(mode) {
      manage();
      connected();
      integration = { ...integration, overwrites: mode };
      return mode;
    },
  };
}
