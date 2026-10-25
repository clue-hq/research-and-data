import type { ReactNode } from "react";
import Link from "next/link";
import { ChevronLeft } from "lucide-react";
import type { SettingsSection } from "../model/settings";
import { SettingsSidebar } from "./settings-sidebar";
import { SettingsMobileNavigation } from "./settings-mobile-navigation";
import styles from "./settings.module.css";
const titles = {
  profile: "Profile",
  connections: "Connections",
  "mcp-server": "MCP server",
  workspace: "Workspace",
  members: "Members",
  integrations: "Integrations",
  pages: "Pages",
  "data-model": "Data Model",
  billing: "Billing",
};
export function SettingsScreen({
  section,
  children,
  dataModelEntityName,
}: {
  section: SettingsSection;
  children: ReactNode;
  dataModelEntityName?: string;
}) {
  const staticSection = ["connections", "mcp-server"].includes(section);
  const nestedDataModel = section === "data-model" && dataModelEntityName;
  return (
    <div className={styles.settingsShell}>
      <SettingsSidebar activeSection={section} />
      <main className={styles.settingsMain}>
        <header className={styles.settingsHeader}>
          <div className={styles.settingsHeaderRow}>
            <SettingsMobileNavigation activeSection={section} />
            <div>
              {nestedDataModel ? (
                <Link
                  className={styles.headerBackLink}
                  href="/settings/data-model"
                  prefetch={false}
                >
                  <ChevronLeft size={13} strokeWidth={1.4} />
                  Data Model
                </Link>
              ) : null}
              <h1>{nestedDataModel || titles[section]}</h1>
            </div>
          </div>
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
