import Link from "next/link";
import {
  adminSettingsNavigation,
  personalSettingsNavigation,
  type SettingsNavigationItem,
} from "../config/settings-navigation";
import type { SettingsSection } from "../model/settings";
import styles from "./settings.module.css";
import { SettingsNavIcon } from "./settings-nav-icon";

function NavigationItems({
  activeSection,
  items,
  onNavigate,
}: {
  activeSection: SettingsSection;
  items: SettingsNavigationItem[];
  onNavigate?: () => void;
}) {
  return items.map((item) => {
    const active = item.section === activeSection;

    return (
      <Link
        aria-current={active ? "page" : undefined}
        className={active ? styles.navigationItemActive : styles.navigationItem}
        href={item.href}
        key={item.href}
        onNavigate={onNavigate}
        prefetch={false}
      >
        <SettingsNavIcon name={item.icon} />
        <span>{item.label}</span>
      </Link>
    );
  });
}

export function SettingsSidebar({
  activeSection,
}: {
  activeSection: SettingsSection;
}) {
  return (
    <aside className={styles.settingsSidebar}>
      <SettingsNavigation activeSection={activeSection} />
    </aside>
  );
}

export function SettingsNavigation({
  activeSection,
  onNavigate,
}: {
  activeSection: SettingsSection;
  onNavigate?: () => void;
}) {
  return (
    <nav
      aria-label="Settings navigation"
      className={styles.settingsNavigation}
    >
      <Link
        className={styles.backItem}
        href="/"
        onNavigate={onNavigate}
        prefetch={false}
      >
        <SettingsNavIcon name="back" />
        <span>Back to home</span>
      </Link>

      <div className={styles.navigationGroup}>
        <NavigationItems
          activeSection={activeSection}
          items={personalSettingsNavigation}
          onNavigate={onNavigate}
        />
      </div>

      <div className={styles.navigationGroup}>
        <p className={styles.navigationCaption}>Admin</p>
        <NavigationItems
          activeSection={activeSection}
          items={adminSettingsNavigation}
          onNavigate={onNavigate}
        />
      </div>
    </nav>
  );
}
