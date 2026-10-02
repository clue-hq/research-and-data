import type { SettingsSection } from "../model/settings";

export type SettingsNavigationIcon =
  | "back"
  | "profile"
  | "connections"
  | "mcp"
  | "workspace"
  | "members"
  | "integrations"
  | "pages"
  | "data-model"
  | "billing";

export interface SettingsNavigationItem {
  href: string;
  icon: SettingsNavigationIcon;
  label: string;
  section: SettingsSection;
}

export const personalSettingsNavigation: SettingsNavigationItem[] = [
  {
    href: "/settings/profile",
    icon: "profile",
    label: "Profile",
    section: "profile",
  },
  {
    href: "/settings/connections",
    icon: "connections",
    label: "Connections",
    section: "connections",
  },
  {
    href: "/settings/mcp-server",
    icon: "mcp",
    label: "MCP server",
    section: "mcp-server",
  },
];

export const adminSettingsNavigation: SettingsNavigationItem[] = [
  {
    href: "/settings/workspace",
    icon: "workspace",
    label: "Workspace",
    section: "workspace",
  },
  {
    href: "/settings/members",
    icon: "members",
    label: "Members",
    section: "members",
  },
  {
    href: "/settings/integrations",
    icon: "integrations",
    label: "Integrations",
    section: "integrations",
  },
  { href: "/settings/pages", icon: "pages", label: "Pages", section: "pages" },
  {
    href: "/settings/data-model",
    icon: "data-model",
    label: "Data Model",
    section: "data-model",
  },
  {
    href: "/settings/billing",
    icon: "billing",
    label: "Billing",
    section: "billing",
  },
];
