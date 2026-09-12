import type { SidebarProject } from "@/features/projects/model/sidebar-project";
import styles from "./project-sidebar-tree.module.css";
import { SidebarFigmaIcon } from "./sidebar-figma-icon";

interface ProjectSidebarActionsMenuProps {
  onArchive: () => void;
  onEdit?: () => void;
  onNewChat: () => void;
  onTogglePinned?: () => void;
  project: SidebarProject;
}

export function ProjectSidebarActionsMenu({
  onArchive,
  onEdit,
  onNewChat,
  onTogglePinned,
  project,
}: ProjectSidebarActionsMenuProps) {
  const actions = [
    { icon: "sidebar-new-chat", label: "New chat", onSelect: onNewChat },
    ...(onTogglePinned ? [{
      icon: "sidebar-pin",
      label: project.pinned ? "Unpin project" : "Pin project",
      onSelect: onTogglePinned,
    }] : []),
    ...(onEdit ? [{
      icon: "sidebar-edit-project",
      label: "Rename project",
      onSelect: onEdit,
    }] : []),
    {
      icon: "sidebar-archive",
      label: "Archive chats",
      onSelect: onArchive,
    },
  ];

  return (
    <div
      aria-label={`${project.title} actions`}
      className={styles.projectMenu}
      role="menu"
    >
      {actions.map((action) => (
        <button
          className={styles.projectMenuItem}
          key={action.label}
          onClick={action.onSelect}
          role="menuitem"
          type="button"
        >
          <SidebarFigmaIcon name={action.icon} />
          <span>{action.label}</span>
        </button>
      ))}
    </div>
  );
}
