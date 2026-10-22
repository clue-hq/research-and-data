import { z } from "zod";

/**
 * The CRM connect flow's wire shapes (spec docs/superpowers/specs/crm-integration/, R-3.10).
 *
 * The connect card is drawn from the `connect_crm` tool's own result (snake_case, as every tool
 * output is); the `/frontend/v1/crm/*` routes answer in camelCase like the rest of the read API.
 */
export const CrmProviderSchema = z.enum(["hubspot", "salesforce"]);
export type CrmProvider = z.infer<typeof CrmProviderSchema>;

export const CRM_PROVIDER_NAMES: Record<CrmProvider, string> = {
  hubspot: "HubSpot",
  salesforce: "Salesforce",
};

export const ConnectCrmOutputSchema = z.object({
  state: z.enum(["connected", "card"]),
  mode: z.enum(["connect", "reconnect", "switch"]).nullable(),
  request_id: z.string().uuid().nullable(),
  providers: z.array(CrmProviderSchema),
  can_connect: z.boolean(),
  connection: z
    .object({
      provider: CrmProviderSchema,
      status: z.string(),
      connected_at: z.string(),
      connected_by_user_id: z.string(),
    })
    .nullable(),
});
export type ConnectCrmOutput = z.infer<typeof ConnectCrmOutputSchema>;

/** The workspace's connection as the card first saw it (the tool's own snapshot). */
export interface CrmConnectionSnapshot {
  provider: CrmProvider;
  status: string;
  connectedAt: string;
}

/** The card's own data, when a finished `connect_crm` call asked for one. */
export interface CrmConnectCardModel {
  requestId: string;
  mode: "connect" | "reconnect" | "switch";
  providers: CrmProvider[];
  canConnect: boolean;
  currentProvider: CrmProvider | null;
  /** What was connected when the card was shown; a switch is done only once this changes. */
  initialConnection: CrmConnectionSnapshot | null;
}

/**
 * The card from a streamed `connect_crm` tool part. The part's output is the governed receipt;
 * the tool's own result is its `reference_values`.
 */
export function crmConnectCard(output: unknown): CrmConnectCardModel | null {
  const values =
    output && typeof output === "object" && "reference_values" in output
      ? (output as { reference_values: unknown }).reference_values
      : output;
  const parsed = ConnectCrmOutputSchema.safeParse(values);
  if (!parsed.success || parsed.data.state !== "card" || parsed.data.request_id === null) {
    return null;
  }
  return {
    requestId: parsed.data.request_id,
    mode: parsed.data.mode ?? "connect",
    providers: parsed.data.providers,
    canConnect: parsed.data.can_connect,
    currentProvider: parsed.data.connection?.provider ?? null,
    initialConnection: parsed.data.connection
      ? {
          provider: parsed.data.connection.provider,
          status: parsed.data.connection.status,
          connectedAt: parsed.data.connection.connected_at,
        }
      : null,
  };
}

/** `GET /frontend/v1/crm/connection`: the workspace's CRM connection, if any. */
export const CrmConnectionResponseSchema = z.union([
  z.object({ status: z.literal("none") }),
  z.object({
    provider: CrmProviderSchema,
    status: z.enum(["active", "expired", "disconnected"]),
    connectedAt: z.string(),
    connectedBy: z.string(),
    connectedByName: z.string().nullable().optional(),
  }),
]);
export type CrmConnectionResponse = z.infer<typeof CrmConnectionResponseSchema>;

/** A connection the card can show as done. */
export interface CrmConnectedState {
  provider: CrmProvider;
  connectedAt: string;
  connectedByName: string | null;
}

/**
 * Whether this connection answers this card. Connect and reconnect cards are answered by any
 * active connection; a switch card only by one that differs from the connection it was shown for.
 */
export function crmConnectionAnswersCard(
  beforeStatus: string | null,
  beforeConnectedAt: string | null,
  connection: CrmConnectionResponse,
): CrmConnectedState | null {
  if (connection.status !== "active") return null;
  if (beforeStatus === "active" && sameMoment(beforeConnectedAt, connection.connectedAt)) {
    return null;
  }
  return {
    provider: connection.provider,
    connectedAt: connection.connectedAt,
    connectedByName: connection.connectedByName ?? null,
  };
}

/**
 * Whether two timestamps name the same moment. The tool's snapshot and the connection route
 * write UTC differently ("…Z" and "…+00:00"), so text equality is not enough.
 */
function sameMoment(a: string | null, b: string): boolean {
  if (a === null) return false;
  const left = Date.parse(a);
  const right = Date.parse(b);
  return Number.isFinite(left) && Number.isFinite(right) ? left === right : a === b;
}

/** What the callback tab tells an open connect card (same browser, `BroadcastChannel`). */
export const CRM_CONNECT_CHANNEL = "clue-crm-connect";
export interface CrmConnectBroadcast {
  requestId: string;
  outcome: CompleteResponse["outcome"];
  provider: CrmProvider | null;
}

export const ConnectLinkResponseSchema = z.object({
  redirectUrl: z.string().url(),
  expiresAt: z.string().nullable(),
});

export const CompleteResponseSchema = z.object({
  outcome: z.enum(["connected", "failed", "stale"]),
  provider: CrmProviderSchema.optional(),
});
export type CompleteResponse = z.infer<typeof CompleteResponseSchema>;

/** A connect click the backend refused, with a message fit to show on the card. */
export class CrmConnectError extends Error {
  constructor(
    message: string,
    readonly code: string,
  ) {
    super(message);
  }
}
