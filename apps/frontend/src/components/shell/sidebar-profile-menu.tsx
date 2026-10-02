"use client";

import Image from "next/image";
import Link from "next/link";
import { Menu } from "@base-ui/react/menu";
import { Check, ChevronRight } from "lucide-react";
import { DesignIcon } from "@/components/ui/design-icon";
import styles from "./app-sidebar.module.css";
import { workspaceInitials } from "@/features/accounts/model/workspace-profile";
import { useWorkspaceProfile } from "./workspace-profile-context";
import { useWorkspaceSwitcher } from "./workspace-switcher-context";

/** The company's logo in the workspace avatar box, or its initials when it has none.
 * unoptimized: Brandfetch's Logo API is embed-only, loaded by the browser itself. */
function WorkspaceMark({ initials, logoUrl }: { initials: string; logoUrl?: string | null }) {
  return logoUrl ? <Image alt="" height={16} src={logoUrl} unoptimized width={16} /> : <>{initials}</>;
}

export function SidebarProfileMenu({ collapsed }: { collapsed: boolean }) {
  const { activeWorkspace, selectWorkspace, workspaces } = useWorkspaceSwitcher();
  // The protected layout supplies the authenticated profile across the app and
  // hands the switcher the signed-in user's memberships by name. A person with
  // one workspace has nothing to choose, so the submenu is disabled.
  const profile = useWorkspaceProfile();
  if (!profile) return null;
  const workspaceName = activeWorkspace?.name ?? profile.workspaceName ?? "Clue workspace";
  const workspaceMark = activeWorkspace?.initials ?? workspaceInitials(workspaceName);

  return (
    <div className={styles.profileRoot}>
      <Menu.Root>
        <Menu.Trigger
          aria-label="Open profile menu"
          className={collapsed ? styles.profileCollapsed : styles.profileTrigger}
        >
          <span className={styles.profileAvatar}>{profile.initials}</span>
          {!collapsed ? (
            <>
              <span className={styles.profileName}>{profile.displayName}</span>
              <DesignIcon className="ml-auto" name="chevron-down" size={12} />
            </>
          ) : null}
        </Menu.Trigger>
        <Menu.Portal>
          <Menu.Positioner
            align="start"
            alignOffset={8}
            className={styles.profileMenuPositioner}
            side="top"
            sideOffset={6}
          >
            <Menu.Popup aria-label="Profile menu" className={styles.profileMenu}>
              <div className={styles.profileMenuIdentity}>
                <span className={styles.profileAvatar}>{profile.initials}</span>
                <div>
                  <p>{profile.displayName}</p>
                  <span>{workspaceName}</span>
                </div>
              </div>
              <Menu.SubmenuRoot>
                <Menu.SubmenuTrigger
                  aria-label={`${workspaceName}, switch workspace`}
                  className={styles.profileMenuItem}
                  disabled={workspaces.length === 0}
                  label={workspaceName}
                  title={
                    workspaces.length === 0
                      ? "Workspace switching is not available yet"
                      : undefined
                  }
                >
                  <span aria-hidden="true" className={styles.workspaceTriggerAvatar}>
                    <WorkspaceMark initials={workspaceMark} logoUrl={activeWorkspace?.logoUrl} />
                  </span>
                  <span className={styles.workspaceTriggerName}>{workspaceName}</span>
                  <ChevronRight aria-hidden="true" className={styles.profileMenuChevron} size={13} />
                </Menu.SubmenuTrigger>
                <Menu.Portal>
                  <Menu.Positioner
                    align="end"
                    className={styles.profileMenuPositioner}
                    collisionPadding={8}
                    sideOffset={8}
                  >
                    <Menu.Popup aria-label="Switch workspace" className={styles.profileMenu}>
                      <Menu.Group aria-label="Workspaces">
                        <Menu.RadioGroup value={activeWorkspace?.id} onValueChange={selectWorkspace}>
                          {workspaces.map((workspace) => (
                            <Menu.RadioItem
                              className={styles.workspaceMenuItem}
                              closeOnClick
                              key={workspace.id}
                              label={workspace.name}
                              value={workspace.id}
                            >
                              <span aria-hidden="true" className={styles.workspaceAvatar}><WorkspaceMark initials={workspace.initials} logoUrl={workspace.logoUrl} /></span>
                              <span className={styles.workspaceMenuDetails}>
                                <span>{workspace.name}</span>
                                <span className={styles.workspaceMenuRole}>{workspace.role}</span>
                              </span>
                              <Menu.RadioItemIndicator className={styles.workspaceMenuCheck}>
                                <Check aria-hidden="true" size={14} />
                              </Menu.RadioItemIndicator>
                            </Menu.RadioItem>
                          ))}
                        </Menu.RadioGroup>
                      </Menu.Group>
                    </Menu.Popup>
                  </Menu.Positioner>
                </Menu.Portal>
              </Menu.SubmenuRoot>
              <Menu.LinkItem className={styles.profileMenuItem} render={<Link href="/settings/profile" prefetch={false} />}>
                <DesignIcon name="settings" size={13} />
                Settings
              </Menu.LinkItem>
            </Menu.Popup>
          </Menu.Positioner>
        </Menu.Portal>
      </Menu.Root>
    </div>
  );
}
