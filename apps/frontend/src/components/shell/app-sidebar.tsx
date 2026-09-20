"use client";

import Link from "next/link";
import { DesignIcon } from "@/components/ui/design-icon";
import {
  primaryNavigation,
  workspaceNavigation,
  type SidebarNavigationItem,
} from "@/config/navigation";
import { useSidebarProjectsController } from "@/features/projects/hooks/use-sidebar-projects-controller";
import styles from "./app-sidebar.module.css";
import { EditProjectDialog } from "./edit-project-dialog";
import { ProjectSidebarTree } from "./project-sidebar-tree";
import { SidebarIcon } from "./sidebar-icon";
import { SidebarProfileMenu } from "./sidebar-profile-menu";
import { useLocalWorkspaceLabel } from "@/features/session/components/local-workspace-provider";

function NavigationGroup({
  activeHref,
  collapsed,
  items,
}: {
  activeHref: string;
  collapsed: boolean;
  items: SidebarNavigationItem[];
}) {
  return (
    <nav aria-label="Workspace navigation">
      {items.map((item) => {
        const active = item.href === activeHref;

        return (
          <Link
            aria-current={active ? "page" : undefined}
            aria-label={collapsed ? item.label : undefined}
            className={`${active ? styles.sidebarItemActive : styles.sidebarItem} flex h-[var(--clue-ds-product-dimension-sidebar-item-height)] items-center rounded-[4px] transition-[background-color,color,padding,gap] ${collapsed ? "justify-center gap-0 px-0" : "gap-2 px-2"} ${
              active
                ? "bg-[var(--clue-background-pressed)] text-[var(--clue-content-neutral)]"
                : "text-[var(--clue-content-subtle)] hover:bg-[var(--clue-background-hover)]"
            }`}
            href={item.href}
            key={item.href}
            prefetch={false}
          >
            <SidebarIcon name={item.icon} />
            <span className={collapsed ? "sr-only" : undefined}>{item.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}

export function AppSidebar({
  activeHref,
  className = "",
  collapsed = false,
  id,
  onToggle,
  toggleLabel,
}: {
  activeHref: string;
  className?: string;
  collapsed?: boolean;
  id?: string;
  onToggle?: (trigger: HTMLButtonElement) => void;
  toggleLabel?: string;
}) {
  const projectsController = useSidebarProjectsController();
  const localWorkspace = useLocalWorkspaceLabel();

  return (
    <>
      <aside
        aria-label="Main navigation"
        className={`flex h-full shrink-0 flex-col overflow-hidden border-r border-[var(--clue-ds-color-border-subtle)] bg-[var(--clue-ds-color-bg-neutral)] transition-[width] duration-200 ease-out ${className}`}
        data-collapsed={collapsed}
        id={id}
        style={{ width: collapsed ? 56 : "var(--clue-ds-product-dimension-sidebar-width)" }}
      >
        <div className={`flex h-[var(--clue-ds-product-dimension-sidebar-header-height)] shrink-0 items-center transition-[padding] duration-200 ${collapsed ? "px-2" : "px-4"}`}>
          {/* Preserve the exact Figma SVG while presenting it at the clearer
              65.33 × 16 product-header size. */}
          <span className={`block h-4 overflow-hidden transition-[width] duration-200 ${collapsed ? "w-4" : "w-[65.333px]"}`}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              alt="Clue"
              className="block h-4 w-[65.333px] max-w-none"
              height={16}
              src="/logos/clue-sidebar.svg"
              width={65.333}
            />
          </span>
          <button
            aria-label={
              toggleLabel ?? (collapsed ? "Expand sidebar" : "Collapse sidebar")
            }
            className="ml-auto flex size-6 items-center justify-center rounded-[4px] hover:bg-[var(--clue-background-hover)]"
            onClick={(event) => onToggle?.(event.currentTarget)}
            type="button"
          >
            <DesignIcon className={`transition-transform duration-200 ${collapsed ? "rotate-180" : ""}`} name="sidebar-toggle" size={12} />
          </button>
        </div>

        {localWorkspace ? (
          <div
            aria-label={`Workspace: ${localWorkspace.name}`}
            className="mx-2 mb-3 shrink-0 rounded-md border border-[var(--clue-border-neutral)] bg-[var(--clue-background-page)] px-2 py-2"
            title={`${localWorkspace.name} · localhost:${localWorkspace.port}`}
          >
            <p className="truncate text-sm font-medium">{collapsed ? localWorkspace.name.slice(0, 1) : localWorkspace.name}</p>
            {!collapsed ? <p className="text-xs text-[var(--clue-content-subtle)]">Local · {localWorkspace.port}</p> : null}
          </div>
        ) : null}

        <div className="clue-scrollbar-hidden min-h-0 flex-1 overflow-y-auto px-2">
          <NavigationGroup activeHref={activeHref} collapsed={collapsed} items={primaryNavigation} />
          <div className="h-3" />
          <NavigationGroup activeHref={activeHref} collapsed={collapsed} items={workspaceNavigation} />
          {!collapsed ? <ProjectSidebarTree controller={projectsController} /> : null}
        </div>

        <SidebarProfileMenu collapsed={collapsed} />
      </aside>

      {projectsController.editProject ? (
        <EditProjectDialog
          canSave={projectsController.canSaveProject}
          error={projectsController.editProjectError}
          saving={projectsController.savingProject}
          name={projectsController.editProjectName}
          onCancel={projectsController.cancelEditProject}
          onChangeName={projectsController.setEditProjectName}
          onRemove={projectsController.archiveProject}
          onSave={projectsController.saveEditProject}
        />
      ) : null}
    </>
  );
}
