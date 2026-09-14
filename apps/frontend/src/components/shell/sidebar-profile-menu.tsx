"use client";

import Link from "next/link";
import { DesignIcon } from "@/components/ui/design-icon";
import styles from "./app-sidebar.module.css";
import { useSidebarProfileMenu } from "./use-sidebar-profile-menu";
import { useWorkspaceProfile } from "./workspace-profile-context";

export function SidebarProfileMenu({ collapsed }: { collapsed: boolean }) {
  const { close, open, rootRef, triggerRef, show, toggle } =
    useSidebarProfileMenu();
  // The protected layout supplies the authenticated profile across the app.
  const profile = useWorkspaceProfile();
  if (!profile) return null;

  if (collapsed) {
    return (
      <Link
        aria-label="Open settings"
        className={styles.profileCollapsed}
        href="/settings/profile"
        prefetch={false}
      >
        <span className={styles.profileAvatar}>{profile.initials}</span>
      </Link>
    );
  }

  return (
    <div className={styles.profileRoot} ref={rootRef}>
      {open ? (
        <div
          aria-label="Profile menu"
          className={styles.profileMenu}
          role="menu"
        >
          <div className={styles.profileMenuIdentity}>
            <span className={styles.profileAvatar}>{profile.initials}</span>
            <div>
              <p>{profile.displayName}</p>
              <span>{profile.workspaceName ?? ""}</span>
            </div>
          </div>
          <Link
            className={styles.profileMenuItem}
            href="/settings/profile"
            onClick={close}
            prefetch={false}
            role="menuitem"
          >
            <DesignIcon name="settings" size={13} />
            Settings
          </Link>
        </div>
      ) : null}

      <button
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label="Open profile menu"
        className={styles.profileTrigger}
        onClick={toggle}
        onKeyDown={(event) => {
          if (event.key === "ArrowUp" || event.key === "ArrowDown") {
            event.preventDefault();
            show();
          }
        }}
        ref={triggerRef}
        type="button"
      >
        <span className={styles.profileAvatar}>{profile.initials}</span>
        <span className={styles.profileName}>{profile.displayName}</span>
        <DesignIcon className="ml-auto" name="chevron-down" size={12} />
      </button>
    </div>
  );
}
