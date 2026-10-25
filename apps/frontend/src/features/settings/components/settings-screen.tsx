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
  nested,
}: {
  section: SettingsSection;
  children: ReactNode;
  /** A page under a section (a Data model entity, a connected CRM): back link + its own title. */
  nested?: { title: string; backHref: string };
}) {
  const staticSection = ["connections", "mcp-server"].includes(section);
  return (
    <div className={styles.settingsShell}>
      <SettingsSidebar activeSection={section} />
      <main className={styles.settingsMain}>
        <header className={styles.settingsHeader}>
          <div className={styles.settingsHeaderRow}>
            <SettingsMobileNavigation activeSection={section} />
            <div>
              {nested ? (
                <Link
                  className={styles.headerBackLink}
                  href={nested.backHref}
                  prefetch={false}
                >
                  <ChevronLeft size={13} strokeWidth={1.4} />
                  {titles[section]}
                </Link>
              ) : null}
              <h1>{nested?.title ?? titles[section]}</h1>
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
