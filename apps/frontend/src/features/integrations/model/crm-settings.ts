import { z } from "zod";
import { CRM_PROVIDER_NAMES, CrmProviderSchema, type CrmProvider } from "./crm";

/**
 * Settings → Integrations: the wire shapes of the `/frontend/v1/crm` Settings routes
 * (`platform/api/clue_api/crm/settings_view.py`, `frontend_read/crm.py`; contract
 * `apps/frontend/docs/api-contracts/crm-settings.md`) and the words the research section shows
 * (Figma `NcLl2r0dzVDN28xAQCwvM1`, board 07 "Connection & agent setup states", node `2310:2463`).
 */

export const CRM_RESEARCH_STATES = [
  "approval_needed",
  "preparing",
  "ready",
  "needs_attention",
  "permission_needed",
  "couldnt_finish",
  "not_connected",
] as const;
export const CrmResearchStateSchema = z.enum(CRM_RESEARCH_STATES);
export type CrmResearchState = z.infer<typeof CrmResearchStateSchema>;

export const CrmSetupItemStatusSchema = z.enum([
  "created",
  "pending",
  "permission_needed",
  "missing",
]);
export type CrmSetupItemStatus = z.infer<typeof CrmSetupItemStatusSchema>;

export const CrmOverwritesModeSchema = z.enum(["ask", "follow_grants"]);
export type CrmOverwritesMode = z.infer<typeof CrmOverwritesModeSchema>;

export const CrmConnectModeSchema = z.enum(["connect", "reconnect", "switch"]);
export type CrmConnectMode = z.infer<typeof CrmConnectModeSchema>;

/** One of the four preparations, in the page's order; title and description are the backend's. */
export const CrmSetupItemSchema = z.object({
  key: z.string(),
  title: z.string(),
  description: z.string(),
  status: CrmSetupItemStatusSchema,
});
export type CrmSetupItem = z.infer<typeof CrmSetupItemSchema>;

export const CrmIntegrationConnectionSchema = z.object({
  provider: CrmProviderSchema,
  status: z.enum(["active", "expired", "disconnected"]),
  /** HubSpot `Portal <id>`, Salesforce the organization's name (R-15.3). */
  accountLabel: z.string(),
  connectedByName: z.string().nullable(),
  connectedAt: z.string(),
});
export type CrmIntegrationConnection = z.infer<typeof CrmIntegrationConnectionSchema>;

export const CrmReviewChatSchema = z.object({ projectId: z.string(), threadId: z.string() });
export type CrmReviewChat = z.infer<typeof CrmReviewChatSchema>;

export const CrmResearchSchema = z
  .object({
    state: CrmResearchStateSchema,
    /** The Clue label of the deleted field, in `needs_attention` only. */
    failedField: z.string().nullable(),
    /** The backend's plain sentence for a blocked state; null otherwise. */
    reason: z.string().nullable(),
    /** The unanswered setup card's chat; set only in `approval_needed` (Task 3 ruling). */
    reviewChat: CrmReviewChatSchema.nullable(),
    items: z.array(CrmSetupItemSchema),
  })
  .refine((research) => research.reviewChat === null || research.state === "approval_needed", {
    message: "reviewChat is set only in approval_needed",
    path: ["reviewChat"],
  });
export type CrmResearch = z.infer<typeof CrmResearchSchema>;

export const CrmStandingPermissionSchema = z.object({
  grantId: z.string(),
  /** Imperative and plain, e.g. "Always set Clue fit level on companies". */
  description: z.string(),
  grantedByName: z.string().nullable(),
  grantedAt: z.string(),
});
export type CrmStandingPermission = z.infer<typeof CrmStandingPermissionSchema>;

/** `GET /frontend/v1/crm/integration`: everything Settings → Integrations shows. */
export const CrmIntegrationSchema = z.object({
  /** The latest connection; a disconnected one is still returned with status "disconnected". */
  connection: CrmIntegrationConnectionSchema.nullable(),
  /** The reader holds `workspace.manage_settings` (owners and admins). */
  canManage: z.boolean(),
  research: CrmResearchSchema,
  permissions: z.array(CrmStandingPermissionSchema),
  overwrites: CrmOverwritesModeSchema,
  /** Where "Ask Clue to …" opens a new chat; null when the workspace has no open project. */
  askClueProjectId: z.string().nullable(),
});
export type CrmIntegration = z.infer<typeof CrmIntegrationSchema>;

export const CrmConnectRequestResponseSchema = z.object({ requestId: z.string().uuid() });
export const CrmDisconnectResponseSchema = z.object({ outcome: z.literal("disconnected") });
export const CrmRevokeResponseSchema = z.object({
  outcome: z.enum(["revoked", "already_revoked"]),
});
export type CrmRevokeOutcome = z.infer<typeof CrmRevokeResponseSchema>["outcome"];
export const CrmOverwritesResponseSchema = z.object({ overwrites: CrmOverwritesModeSchema });

// --- The research section's words (board 07) ---------------------------------------------------

/**
 * The research section's one action. `review_request` opens `reviewChat` when there is one, and
 * otherwise — like every `ask_clue` action — `/projects/{askClueProjectId}?prompt=<askClueMessage>`
 * with the message prefilled, never sent (R-15.2).
 */
export interface CrmResearchAction {
  kind: "review_request" | "ask_clue";
  label: string;
  askClueMessage: string;
}

/** The read-only explanation "View details" opens. */
export interface CrmResearchDetails {
  heading: string;
  intro: string;
  columns: { item: string; progress: string };
  blocking: { heading: string; body: string } | null;
  nextSteps: { heading: string; body: string } | null;
  /** One paragraph; when present it carries the read-only line and `footer` is null. */
  whereToFind: { heading: string; body: string } | null;
  footer: string | null;
}

export interface CrmResearchStateCopy {
  /** "Research in HubSpot". */
  sectionTitle: string;
  statusLabel: string;
  title: string;
  /** The line under the title while the details are closed. */
  body: string;
  /** The same line while the details are open (only permission needed words it differently). */
  expandedBody: string;
  /** The line a member (no manage permission) reads instead of `body`. */
  memberBody: string;
  action: CrmResearchAction | null;
  showDetailsLabel: string;
  hideDetailsLabel: string;
  details: CrmResearchDetails;
}

/** What Salesforce calls a company. */
function companyWord(provider: CrmProvider): string {
  return provider === "salesforce" ? "account" : "company";
}

function objectsOf(items: readonly CrmSetupItem[], status: CrmSetupItemStatus) {
  const objects = new Set<"company" | "contact">();
  for (const item of items) {
    if (item.status !== status) continue;
    if (item.key.startsWith("company")) objects.add("company");
    else if (item.key.startsWith("contact")) objects.add("contact");
  }
  return [...objects];
}

/** "contact", "account", "account and contact" — or null when no item names the records. */
function refusedRecords(provider: CrmProvider, items: readonly CrmSetupItem[]): string | null {
  const objects = objectsOf(items, "permission_needed");
  if (objects.length === 0) return null;
  return objects
    .sort()
    .map((object) => (object === "company" ? companyWord(provider) : "contact"))
    .join(" and ");
}

function lowerFirst(text: string): string {
  return text.charAt(0).toLowerCase() + text.slice(1);
}

const FOOTER =
  "Details are read-only. Record updates follow your chat approvals and standing permissions.";

/**
 * The research section's title, body and button for `state`, as board 07 words them.
 *
 * `items` (the backend's four preparations) name the deleted item in `needs_attention` and the
 * refused records in `permission_needed`; `failedField` (the backend's Clue label of the deleted
 * field) names it in the "Ask Clue to restore" message.
 */
export function researchStateCopy(
  state: CrmResearchState,
  provider: CrmProvider,
  items: readonly CrmSetupItem[] = [],
  failedField: string | null = null,
): CrmResearchStateCopy {
  const crm = CRM_PROVIDER_NAMES[provider];
  const company = companyWord(provider);
  const finishMessage = `Finish setting up Clue’s fields in ${crm}.`;
  const details: CrmResearchDetails = {
    heading: `${crm} preparation details`,
    intro: `Clue adds fields to your ${company} and contact records so approved research can be saved there. Creating fields does not write research values.`,
    columns: { item: "What Clue is preparing", progress: "Progress" },
    blocking: null,
    nextSteps: null,
    whereToFind: null,
    footer: FOOTER,
  };
  const base = {
    sectionTitle: `Research in ${crm}`,
    showDetailsLabel: "View details ▾",
    hideDetailsLabel: "Hide details ▴",
  };
  const plain = (
    statusLabel: string,
    title: string,
    body: string,
    action: CrmResearchAction | null,
    extra: Partial<CrmResearchStateCopy> = {},
  ): CrmResearchStateCopy => ({
    ...base,
    statusLabel,
    title,
    body,
    expandedBody: body,
    memberBody: body,
    action,
    details,
    ...extra,
  });

  switch (state) {
    // 2310:2501; member view 2310:2552.
    case "approval_needed":
      return plain(
        "Approval needed",
        `Clue needs permission to prepare ${crm} for your research.`,
        "An owner or admin can review the request in chat. Once approved, Clue creates and checks the required fields.",
        {
          kind: "review_request",
          label: "Review request",
          askClueMessage: `Set up Clue’s fields in ${crm}.`,
        },
        { memberBody: "Clue is waiting for an owner or admin to approve preparation in chat." },
      );
    // 2310:2518.
    case "preparing":
      return plain(
        "Preparing",
        `Clue is preparing ${crm}…`,
        `Clue is creating and checking the fields for your research. We’ll show you when ${crm} is ready.`,
        null,
      );
    // 2310:2535.
    case "needs_attention": {
      const missing = items.find((item) => item.status === "missing");
      const tail = "Ask Clue to propose restoring it; an owner or admin approves the request in chat.";
      // The design names the missing preparation; `failedField` (the same field, chosen by the
      // backend in page order) names it in the restore message.
      const [title, body] = missing
        ? [
            `${missing.title} can’t be saved.`,
            `The field Clue uses for ${lowerFirst(missing.title)} was deleted in ${crm}. ${tail}`,
          ]
        : failedField
          ? [
              `“${failedField}” can’t be saved.`,
              `Clue’s “${failedField}” field was deleted in ${crm}. ${tail}`,
            ]
          : ["A field Clue uses can’t be saved.", `A field Clue uses was deleted in ${crm}. ${tail}`];
      return plain(
        "Needs attention",
        title,
        body,
        {
          kind: "ask_clue",
          label: "Ask Clue to restore",
          askClueMessage: failedField
            ? `Restore Clue’s “${failedField}” field in ${crm}.`
            : `Restore Clue’s fields in ${crm}.`,
        },
        { details: { ...details, heading: "What Clue has prepared" } },
      );
    }
    // 2338:2403 (closed) and 2338:2477 (details open).
    case "permission_needed": {
      const records = refusedRecords(provider, items);
      return plain(
        "Permission needed",
        `Clue needs help from your ${crm} admin.`,
        `The connected ${crm} user can’t create fields on ${records ?? "these"} records. Your admin needs to grant that access before Clue can finish preparing ${crm}.`,
        { kind: "ask_clue", label: "Ask Clue to retry", askClueMessage: finishMessage },
        {
          expandedBody: records
            ? `Clue couldn’t finish preparing ${records} fields.`
            : `Clue couldn’t finish preparing ${crm}.`,
          details: {
            ...details,
            heading: "What Clue has prepared",
            blocking: {
              heading: "What’s blocking completion",
              body: records
                ? `The connected ${crm} user doesn’t have permission to create ${records} fields.`
                : `The connected ${crm} user doesn’t have permission to create fields on these records.`,
            },
            nextSteps: {
              heading: "What happens next",
              body: `Ask your ${crm} admin to grant that user permission to create fields on ${records ?? "these"} records. An owner or admin can then ask Clue to retry. Clue performs the setup; you don’t need to create fields yourself.`,
            },
          },
        },
      );
    }
    // 2310:2591.
    case "couldnt_finish":
      return plain(
        "Couldn’t finish",
        `Clue couldn’t finish preparing ${crm}.`,
        "Some fields are ready. Clue can retry the remaining setup, with owner or admin approval in chat.",
        { kind: "ask_clue", label: "Ask Clue to retry", askClueMessage: finishMessage },
        { details: { ...details, heading: "What Clue has prepared" } },
      );
    // 2338:2427 (HubSpot), 2338:2538 (Salesforce).
    case "ready":
      return plain(
        "Ready",
        `${crm} is ready to receive your research.`,
        "Clue has prepared the fields for your research. You control updates through chat approvals and the Permissions section below.",
        null,
        {
          details: {
            ...details,
            whereToFind: {
              heading: `Where to find this in ${crm}`,
              body: [
                ...(provider === "salesforce"
                  ? [
                      "Open an account or contact record and look for the fields labelled Clue.",
                      "With your approval, Clue also grants the connected user access to these fields.",
                    ]
                  : ["Open a company or contact record and look for its Clue properties."]),
                FOOTER,
              ].join(" "),
            },
            footer: null,
          },
        },
      );
    // No board: the provider page is shown only for the connected CRM. Plain words, same voice.
    case "not_connected":
      return plain(
        "Not connected",
        `Connect ${crm} to prepare it for your research.`,
        `Once ${crm} is connected, Clue can add the fields your research is saved in, with owner or admin approval in chat.`,
        null,
      );
  }
}

/** The "Progress" column of the details table (board 07: "Created", "Permission needed"). */
export function setupItemStatusLabel(status: CrmSetupItemStatus, provider: CrmProvider): string {
  switch (status) {
    case "created":
      return "Created";
    case "permission_needed":
      return "Permission needed";
    case "pending":
      return "Not created yet";
    case "missing":
      return `Deleted in ${CRM_PROVIDER_NAMES[provider]}`;
  }
}
