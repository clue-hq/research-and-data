import { projectChatHref } from "@/features/chat-shell/model/chat-shell-routes";
import { CRM_PROVIDER_NAMES, type CrmProvider } from "./crm";
import {
  researchStateCopy,
  setupItemStatusLabel,
  type CrmIntegration,
  type CrmOverwritesMode,
  type CrmResearchDetails,
  type CrmResearchState,
  type CrmStandingPermission,
} from "./crm-settings";

/**
 * The provider page `/settings/integrations/{hubspot|salesforce}` (Figma NcLl2r0dzVDN28xAQCwvM1:
 * board 02 HubSpot 2308:1592, board 03 Salesforce 2308:1593, board 07 states 2310:2463, board 06
 * disconnect/overwrite/revoke dialogs 2310:2395 / 2310:2420 / 2310:2442). Pure view models; the
 * components render them as they are.
 */

export const CRM_INTEGRATIONS_HREF = "/settings/integrations";

/**
 * Where the provider page sends the reader instead, or null to show it: only the CRM that is
 * connected (active or expired) has a page; anything else goes back to the overview.
 */
export function crmProviderPageRedirect(
  provider: CrmProvider,
  integration: CrmIntegration,
): string | null {
  const connection = integration.connection;
  if (connection === null || connection.status === "disconnected") return CRM_INTEGRATIONS_HREF;
  return connection.provider === provider ? null : CRM_INTEGRATIONS_HREF;
}

export interface CrmBadge {
  label: string;
  tone: "neutral" | "warning";
}

/** What the CRM calls the connected account (R-15.3). */
function accountWord(provider: CrmProvider): "portal" | "organization" {
  return provider === "salesforce" ? "organization" : "portal";
}

/** "22 Oct 2026" (the boards' date form); empty for an unreadable timestamp. */
export function crmDay(at: string): string {
  const when = new Date(at);
  if (Number.isNaN(when.getTime())) return "";
  return when.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export type CrmConnectionAction = "reconnect" | "change" | "disconnect";

export interface CrmConnectionView {
  provider: CrmProvider;
  name: string;
  badge: CrmBadge;
  /** "Portal" (HubSpot) or "Organization" (Salesforce). */
  accountFieldLabel: string;
  accountLabel: string;
  connectedBy: string | null;
  /** Only an expired connection: the board 07 "Expired" lines. */
  expired: { warning: string; note: string } | null;
  /** Owner/admin actions; none for a member (board 07 member view). */
  actions: CrmConnectionAction[];
  /** A member's line in place of the actions; null for an owner or admin. */
  note: string | null;
}

/** The connection section (boards 02/03 "Connection", board 07 "Expired" and member view). */
export function crmConnectionView(integration: CrmIntegration): CrmConnectionView {
  const connection = integration.connection;
  if (connection === null) throw new Error("The provider page needs a connection.");
  const provider = connection.provider;
  const word = accountWord(provider);
  const expired = connection.status === "expired";
  const manage = integration.canManage;
  return {
    provider,
    name: CRM_PROVIDER_NAMES[provider],
    badge: expired ? { label: "Expired", tone: "warning" } : { label: "Connected", tone: "neutral" },
    accountFieldLabel: word === "portal" ? "Portal" : "Organization",
    accountLabel: connection.accountLabel,
    connectedBy: connection.connectedByName,
    expired: expired
      ? {
          warning: "Your connection expired. Clue can’t read or write until you reconnect.",
          note: `Permissions, fields, and change history are kept when you reconnect the same ${word}.`,
        }
      : null,
    actions: !manage ? [] : expired ? ["reconnect"] : ["reconnect", "change", "disconnect"],
    note: manage ? null : "Ask an owner or admin to reconnect, change, or disconnect this CRM.",
  };
}

const WARNING_STATES: ReadonlySet<CrmResearchState> = new Set([
  "approval_needed",
  "needs_attention",
  "permission_needed",
  "couldnt_finish",
]);

export interface CrmResearchRow {
  key: string;
  title: string;
  description: string;
  progress: string;
  tone: "subtle" | "warning";
}

export interface CrmResearchView {
  sectionTitle: string;
  badge: CrmBadge;
  title: string;
  /** The line under the title with the details closed, and with them open. */
  body: string;
  expandedBody: string;
  /** The one button, already pointing where it goes; null when there is nowhere to go. */
  action: { label: string; href: string } | null;
  showDetailsLabel: string;
  hideDetailsLabel: string;
  details: CrmResearchDetails;
  rows: CrmResearchRow[];
}

function promptHref(projectId: string, message: string): string {
  return `/projects/${encodeURIComponent(projectId)}?prompt=${encodeURIComponent(message)}`;
}

/**
 * The research section (board 07 "Research setup / …"). "Review request" opens the pending setup
 * card's chat; otherwise it, like every "Ask Clue to …", opens the project with the message
 * prefilled (R-15.2). A member gets no button (board 07 member view) and the member wording.
 */
export function crmResearchView(integration: CrmIntegration): CrmResearchView {
  const provider = integration.connection?.provider ?? "hubspot";
  const research = integration.research;
  const copy = researchStateCopy(research.state, provider, research.items, research.failedField);
  let action: CrmResearchView["action"] = null;
  if (integration.canManage && copy.action) {
    const chat = copy.action.kind === "review_request" ? research.reviewChat : null;
    if (chat) action = { label: copy.action.label, href: projectChatHref(chat.projectId, chat.threadId) };
    else if (integration.askClueProjectId) {
      action = {
        label: copy.action.label,
        href: promptHref(integration.askClueProjectId, copy.action.askClueMessage),
      };
    }
  }
  return {
    sectionTitle: copy.sectionTitle,
    badge: { label: copy.statusLabel, tone: WARNING_STATES.has(research.state) ? "warning" : "neutral" },
    title: copy.title,
    body: integration.canManage ? copy.body : copy.memberBody,
    expandedBody: integration.canManage ? copy.expandedBody : copy.memberBody,
    action,
    showDetailsLabel: copy.showDetailsLabel,
    hideDetailsLabel: copy.hideDetailsLabel,
    details: copy.details,
    rows: research.items.map((item) => ({
      key: item.key,
      title: item.title,
      description: item.description,
      progress: setupItemStatusLabel(item.status, provider),
      tone: item.status === "permission_needed" || item.status === "missing" ? "warning" : "subtle",
    })),
  };
}

export interface CrmPermissionsView {
  title: string;
  description: string;
  empty: string;
  rows: { grantId: string; description: string; meta: string }[];
}

/** The standing permissions (boards 02/03 "Permissions", board 07 "Permissions / Empty"). */
export function crmPermissionsView(integration: CrmIntegration): CrmPermissionsView {
  return {
    title: "Permissions",
    description: "Standing permissions granted on approval cards. Any member can revoke them.",
    empty: "No standing permissions. Clue asks on a card each time.",
    rows: integration.permissions.map((grant) => {
      const day = crmDay(grant.grantedAt);
      return {
        grantId: grant.grantId,
        description: grant.description,
        meta: grant.grantedByName ? `Allowed by ${grant.grantedByName} · ${day}` : `Allowed ${day}`,
      };
    }),
  };
}

const GERUNDS: Record<string, string> = {
  set: "setting",
  create: "creating",
  add: "adding",
  remove: "removing",
  mark: "marking",
};

/**
 * "Revoke this permission?" (2310:2442). The body names what Clue will ask about again, turned
 * from the permission's own words ("Always set X" → "setting X"); a permission worded otherwise
 * reads "making these changes".
 */
export function crmRevokeCopy(permission: CrmStandingPermission): { title: string; body: string } {
  const match = /^Always (\w+) (.+)$/.exec(permission.description);
  const gerund = match ? GERUNDS[match[1]] : undefined;
  const what = match && gerund ? `${gerund} ${match[2]}` : "making these changes";
  return {
    title: "Revoke this permission?",
    body: `Clue will ask on a card before ${what} again. Changes already made stay in your CRM.`,
  };
}

const OVERWRITE_LABELS: Record<CrmOverwritesMode, { label: string; description: string }> = {
  ask: { label: "Always ask me", description: "Show a before-and-after preview in chat every time." },
  follow_grants: {
    label: "Follow “Always allow”",
    description: "Allow these changes when a standing permission covers them.",
  },
};

export interface CrmOverwritesView {
  editable: boolean;
  title: string;
  description: string | null;
  options: { mode: CrmOverwritesMode; label: string; description: string; selected: boolean }[];
  note: string;
}

/** The overwrites setting (boards 02/03 "Overwrites"; board 07 member view reads it only). */
export function crmOverwritesView(integration: CrmIntegration): CrmOverwritesView {
  const crm = CRM_PROVIDER_NAMES[integration.connection?.provider ?? "hubspot"];
  if (!integration.canManage) {
    return {
      editable: false,
      title: `Overwrites · ${OVERWRITE_LABELS[integration.overwrites].label}`,
      description: null,
      options: [],
      note: "Only owners and admins can change this setting. You can still revoke standing permissions.",
    };
  }
  return {
    editable: true,
    title: "Overwrites",
    description: `When Clue would change a value a person set in ${crm}:`,
    options: (["ask", "follow_grants"] as const).map((mode) => ({
      mode,
      ...OVERWRITE_LABELS[mode],
      selected: integration.overwrites === mode,
    })),
    note: "Owners and admins can change this setting. Changes save automatically.",
  };
}

/** "Allow changes to people’s values?" (2310:2420), asked before choosing Follow “Always allow”. */
export const CRM_OVERWRITE_CONFIRM_COPY = {
  title: "Allow changes to people’s values?",
  description: "Changes outside those permissions will still need approval in chat.",
  confirm: "Allow these changes",
} as const;

/** "Disconnect HubSpot?" (2310:2395). */
export function crmDisconnectCopy(provider: CrmProvider) {
  const crm = CRM_PROVIDER_NAMES[provider];
  return {
    title: `Disconnect ${crm}?`,
    description: `Clue will stop reading from and writing to this ${accountWord(provider)}.`,
    consequence: `Your “Always allow” permissions will be cleared. Changes Clue already made in ${crm} will stay there. Cards waiting in chats will be closed.`,
  };
}
