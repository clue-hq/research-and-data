import { Menu } from "@base-ui/react/menu";
import { Button } from "@/components/ui/button";
import { SidebarFigmaIcon } from "@/components/shell/sidebar-figma-icon";
import type { DirectoryProject } from "../model/project-directory";
import type { ProjectsScreenController } from "../hooks/use-projects-screen-controller";
import styles from "./projects-directory.module.css";

export function ProjectDirectoryMenu({ project, controller }: { project: DirectoryProject; controller: ProjectsScreenController }) {
  return <Menu.Root><Menu.Trigger render={<Button variant="transparent" size="icon-sm" />} aria-label={`Options for ${project.title}`}><SidebarFigmaIcon name="sidebar-ellipsis" /></Menu.Trigger>
    <Menu.Portal><Menu.Positioner sideOffset={5} align="end" className={styles.menuPositioner}><Menu.Popup className={styles.menu}>
      <Menu.Item className={styles.menuItem} disabled={controller.busy} onClick={() => controller.mutate("pin", project.id)}><SidebarFigmaIcon name="sidebar-pin" />{project.pinned ? "Unpin project" : "Pin project"}</Menu.Item>
      <Menu.Item className={styles.menuItem} disabled={project.status === "archived"} onClick={() => controller.openDialog("details", project)}><SidebarFigmaIcon name="sidebar-edit-project" />Edit details</Menu.Item>
      <Menu.Separator className={styles.menuSeparator} />
      <Menu.Item className={styles.menuItem} disabled={controller.busy} onClick={() => controller.mutate("archive", project.id)}><SidebarFigmaIcon name="sidebar-archive" />{project.status === "archived" ? "Restore project" : "Archive project"}</Menu.Item>
    </Menu.Popup></Menu.Positioner></Menu.Portal>
  </Menu.Root>;
}
