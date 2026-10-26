export type SidebarIconName =
  | "home"
  | "account"
  | "project"
  | "artifacts"
  | "templates"
  | "mail"
  | "email"
  | "analytics"
  | "brand";

export interface SidebarNavigationItem {
  href: string;
  icon: SidebarIconName;
  label: string;
}

export const primaryNavigation: SidebarNavigationItem[] = [
  { href: "/", icon: "home", label: "Home" },
  { href: "/accounts", icon: "account", label: "Account" },
  { href: "/projects", icon: "project", label: "Projects" },
];

export const workspaceNavigation: SidebarNavigationItem[] = [
  { href: "/direct-mail", icon: "mail", label: "Direct mail" },
  { href: "/artifacts", icon: "artifacts", label: "Artifacts" },
  { href: "/templates", icon: "templates", label: "Templates" },
  { href: "/brand-context", icon: "brand", label: "Brand context" },
];

export const v2WorkspaceNavigation: SidebarNavigationItem[] = [
  { href: "/direct-mail", icon: "mail", label: "Direct mail" },
  { href: "/email", icon: "email", label: "Email" },
  { href: "/artifacts", icon: "artifacts", label: "Artifacts" },
  { href: "/analytics", icon: "analytics", label: "Analytics" },
  { href: "/brand-context", icon: "brand", label: "Brand context" },
];
