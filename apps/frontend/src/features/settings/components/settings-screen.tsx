import Link from "next/link";
import { ChevronLeft } from "lucide-react";
import type { PagesSettingsRead } from "../model/pages";
import type { SettingsRoute, SettingsWorkspace } from "../model/settings";
import { BillingSettings } from "./billing-settings";
import { DataModelSettings } from "./data-model-settings";
import { MembersSettings } from "./members-settings";
import { PagesSettings } from "./pages-settings";
import { ProfileSettings } from "./profile-settings";
import { SettingsComingSoon } from "./settings-coming-soon";
import { SettingsSidebar } from "./settings-sidebar";
import styles from "./settings.module.css";
import { WorkspaceSettings } from "./workspace-settings";

const titles = {
  profile: "Profile",
  connections: "Connections",
  "mcp-server": "MCP server",
  workspace: "Workspace",
  members: "Members",
  integrations: "Integrations",
  pages: "Pages",
  "data-model": "Data model",
  billing: "Billing",
} as const;

function SettingsBody({
  canManage,
  pages,
  route,
  workspace,
}: {
  canManage: boolean;
  pages: PagesSettingsRead | null;
  route: SettingsRoute;
  workspace: SettingsWorkspace;
}) {
  switch (route.section) {
    case "profile":
      return <ProfileSettings profile={workspace.profile} />;
    case "connections":
    case "mcp-server":
    case "integrations":
      return <SettingsComingSoon section={route.section} connections={workspace.connections} />;
    case "workspace":
      return <WorkspaceSettings workspace={workspace.workspace} />;
    case "members":
      return <MembersSettings members={workspace.members} />;
    case "pages":
      // The route fetches the Pages read only for this section, so a null here is a
      // routing bug, not an empty workspace: fail loudly into `error.tsx`.
      if (!pages) throw new Error("Settings \u2192 Pages rendered without its read");
      return <PagesSettings canManage={canManage} initial={pages} />;
    case "data-model":
      return (
        <DataModelSettings
          dataModel={workspace.dataModel}
          entity={route.entity}
          view={route.view}
        />
      );
    case "billing":
      return <BillingSettings billing={workspace.billing} />;
  }
}

export function SettingsScreen({
  canManage,
  pages,
  route,
  workspace,
}: {
  canManage: boolean;
  pages: PagesSettingsRead | null;
  route: SettingsRoute;
  workspace: SettingsWorkspace;
}) {
  const nestedDataModel = route.section === "data-model" && route.entity;
  const comingSoon = ["connections", "mcp-server", "integrations"].includes(route.section);
  const title = nestedDataModel
    ? workspace.dataModel.entities.find((entity) => entity.id === route.entity)?.name ?? "Accounts"
    : titles[route.section];

  return (
    <div className={styles.settingsShell}>
      <SettingsSidebar activeSection={route.section} />
      <main className={styles.settingsMain}>
        <header className={styles.settingsHeader}>
          {nestedDataModel ? (
            <Link className={styles.headerBackLink} href="/settings/data-model">
              <ChevronLeft size={13} strokeWidth={1.4} />
              Data model
            </Link>
          ) : null}
          <h1>{title}</h1>
        </header>
        <div className={styles.settingsContentScroll}>
          <div className={comingSoon ? styles.comingSoonBody : styles.settingsBody}>
            <SettingsBody
              canManage={canManage}
              pages={pages}
              route={route}
              workspace={workspace}
            />
          </div>
        </div>
      </main>
    </div>
  );
}
