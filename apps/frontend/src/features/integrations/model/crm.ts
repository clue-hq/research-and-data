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

/** The card's own data, when a finished `connect_crm` call asked for one. */
export interface CrmConnectCardModel {
  requestId: string;
  mode: "connect" | "reconnect" | "switch";
  providers: CrmProvider[];
  canConnect: boolean;
  currentProvider: CrmProvider | null;
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
  };
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
