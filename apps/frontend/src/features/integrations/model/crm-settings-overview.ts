import { CRM_PROVIDER_NAMES, type CrmProvider } from "./crm";
import type { CrmIntegration } from "./crm-settings";

/**
 * The CRM card on Settings → Integrations (Figma NcLl2r0dzVDN28xAQCwvM1: board 01 "Not
 * connected" 2309:1732, board 04 "Connected" 2309:2636, board 05 "Needs attention" 2309:2790).
 *
 * A disconnected connection reads as not connected. A member (no `workspace.manage_settings`)
 * sees the same card without Connect or Reconnect; Manage stays, because every member may open
 * the provider page and revoke standing permissions.
 */

export type CrmOverviewAction = "connect" | "reconnect" | "manage";

export interface CrmOverviewCard {
  state: "not_connected" | "connected" | "expired";
  /** The brand marks at the card's start: both CRMs before one is connected. */
  logos: CrmProvider[];
  title: string;
  badge: { label: string; tone: "neutral" | "warning" } | null;
  lines: { text: string; tone: "subtle" | "warning" }[];
  actions: CrmOverviewAction[];
  /** The provider page (Task 7) the Manage button opens. */
  manageHref: string | null;
}

export const CRM_OVERVIEW_COPY = {
  heading: "Connect your workspace",
  description: "Bring your tools together. You stay in control of what Clue changes.",
  footer: "Clue asks for approval in chat before writing to your CRM.",
} as const;

export function crmOverviewCard(integration: CrmIntegration, now: Date = new Date()): CrmOverviewCard {
  const connection = integration.connection;
  if (connection === null || connection.status === "disconnected") {
    return {
      state: "not_connected",
      logos: ["hubspot", "salesforce"],
      title: "CRM",
      badge: null,
      lines: [
        {
          text: "Connect HubSpot or Salesforce to read your CRM and write research back.",
          tone: "subtle",
        },
      ],
      actions: integration.canManage ? ["connect"] : [],
      manageHref: null,
    };
  }
  const when = connectedSince(connection.connectedAt, now);
  const by = connection.connectedByName
    ? `Connected by ${connection.connectedByName}${when ? ` · ${when}` : ""}`
    : `Connected${when ? ` ${when}` : ""}`;
  const account = { text: `${connection.accountLabel} · ${by}`, tone: "subtle" as const };
  const common = {
    logos: [connection.provider],
    title: CRM_PROVIDER_NAMES[connection.provider],
    manageHref: `/settings/integrations/${connection.provider}`,
  };
  if (connection.status === "expired") {
    return {
      ...common,
      state: "expired",
      badge: { label: "Needs attention", tone: "warning" },
      lines: [account, { text: "Your connection expired. Reconnect to continue.", tone: "warning" }],
      actions: integration.canManage ? ["reconnect", "manage"] : ["manage"],
    };
  }
  return {
    ...common,
    state: "connected",
    badge: { label: "Connected", tone: "neutral" },
    lines: [account],
    actions: ["manage"],
  };
}

const DAY_MS = 24 * 60 * 60 * 1000;

/**
 * "today", "yesterday", "3 days ago" within a week, else "22 Oct 2026" (the boards' two forms).
 * Calendar days in the reader's time zone; `null` for an unreadable timestamp.
 */
export function connectedSince(at: string, now: Date = new Date()): string | null {
  const when = new Date(at);
  if (Number.isNaN(when.getTime())) return null;
  const startOf = (date: Date) => new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
  const days = Math.round((startOf(now) - startOf(when)) / DAY_MS);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 7) return `${days} days ago`;
  return when.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}
