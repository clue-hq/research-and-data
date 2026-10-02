export type SidebarIconName =
  | "home"
  | "account"
  | "project"
  | "artifacts"
  | "templates"
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
  { href: "/artifacts", icon: "artifacts", label: "Artifacts" },
  { href: "/templates", icon: "templates", label: "Templates" },
  { href: "/brand-context", icon: "brand", label: "Brand context" },
];
