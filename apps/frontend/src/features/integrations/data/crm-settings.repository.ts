import { ClueApiError } from "@/features/accounts/data/clue-api-error";
import { ApiErrorEnvelopeSchema } from "@/features/accounts/model/vocabulary";
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
 * `crm_permission_not_found`, `PERMISSION_REQUIRED`.
 */
export interface CrmSettingsRepository {
  getIntegration(): Promise<CrmIntegration>;
  /** Opens (or reuses) a Settings connect request; its id drives the existing connect flow. */
  requestConnect(mode: CrmConnectMode): Promise<string>;
  disconnect(): Promise<void>;
  revokePermission(grantId: string): Promise<CrmRevokeOutcome>;
  setOverwrites(mode: CrmOverwritesMode): Promise<CrmOverwritesMode>;
}

/** The same-origin BFF the connect card's `crm.repository.ts` uses. */
const CRM_PATH = "/api/clue/frontend/v1/crm";

async function refusal(response: Response, path: string): Promise<ClueApiError> {
  let envelope = null;
  try {
    const parsed = ApiErrorEnvelopeSchema.safeParse(await response.json());
    if (parsed.success) envelope = parsed.data.error;
  } catch {
    // A proxy error page is not the backend's envelope.
  }
  return new ClueApiError(
    envelope?.message ?? `Clue API returned ${response.status} for ${path}`,
    {
      code: envelope?.code ?? `HTTP_${response.status}`,
      requestId: envelope?.requestId ?? response.headers.get("X-Request-Id") ?? null,
      status: response.status,
    },
  );
}

/** The browser adapter, through the authenticated `/api/clue` BFF. */
export function httpCrmSettingsRepository(clueFetch: typeof fetch = fetch): CrmSettingsRepository {
  async function call(path: string, method: string, body?: unknown): Promise<unknown> {
    const response = await clueFetch(`${CRM_PATH}${path}`, {
      method,
      cache: "no-store",
      headers: {
        Accept: "application/json",
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    if (!response.ok) throw await refusal(response, path);
    return response.json();
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
