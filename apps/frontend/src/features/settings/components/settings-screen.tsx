import type { ReactNode } from "react";
import type { SettingsSection } from "../model/settings";
import { SettingsSidebar } from "./settings-sidebar";
import styles from "./settings.module.css";
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
};
export function SettingsScreen({
  section,
  children,
}: {
  section: SettingsSection;
  children: ReactNode;
}) {
  const staticSection = [
    "connections",
    "mcp-server",
    "integrations",
    "billing",
    "pages",
  ].includes(section);
  return (
    <div className={styles.settingsShell}>
      <SettingsSidebar activeSection={section} />
      <main className={styles.settingsMain}>
        <header className={styles.settingsHeader}>
          <h1>{titles[section]}</h1>
        </header>
        <div className={styles.settingsContentScroll}>
          <div
            className={
              staticSection ? styles.comingSoonBody : styles.settingsBody
            }
          >
            {children}
          </div>
        </div>
      </main>
    </div>
  );
}
