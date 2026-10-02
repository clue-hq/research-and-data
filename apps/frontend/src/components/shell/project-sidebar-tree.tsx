import Link from "next/link";
import type { SidebarProjectsController } from "@/features/projects/hooks/use-sidebar-projects-controller";
import styles from "./project-sidebar-tree.module.css";
import { ProjectSidebarActionsMenu } from "./project-sidebar-actions-menu";
import { SidebarConversationStatus } from "./sidebar-conversation-status";
import { SidebarFigmaIcon } from "./sidebar-figma-icon";
import { SidebarMarqueeLabel } from "./sidebar-marquee-label";

function pathnameOf(href: string) {
  return href.split("?")[0];
}

export function ProjectSidebarTree({
  controller,
}: {
  controller: SidebarProjectsController;
}) {
  return (
    <section aria-labelledby="projects-heading" className={styles.projectSection}>
      <h2 className={styles.projectSectionLabel} id="projects-heading">
        Projects
      </h2>

      <nav aria-label="Projects and chats">
        {controller.projects.map((project) => {
          const menuOpen = controller.menuProjectId === project.id;

          return (
            <div className={styles.projectGroup} key={project.id}>
              <div
                className={`${styles.projectRow} ${menuOpen ? styles.projectRowMenuOpen : ""}`}
                data-sidebar-project-menu-root
              >
                <button
                  aria-expanded={project.expanded}
                  className={styles.projectToggle}
                  onClick={() => controller.toggleProject(project.id)}
                  type="button"
                >
                  <SidebarFigmaIcon
                    name={
                      project.expanded
                        ? "sidebar-folder-open"
                        : "sidebar-folder-closed"
                    }
                  />
                  <SidebarMarqueeLabel text={project.title} />
                </button>

                <div className={styles.projectRowActions}>
                  <button
                    aria-label={`New chat in ${project.title}`}
                    className={styles.projectRowAction}
                    onClick={() => controller.createConversation(project.id)}
                    type="button"
                  >
                    <SidebarFigmaIcon name="sidebar-new-chat" />
                  </button>
                  <button
                    aria-expanded={menuOpen}
                    aria-haspopup="menu"
                    aria-label={`More options for ${project.title}`}
                    className={styles.projectRowAction}
                    onClick={() => controller.toggleMenu(project.id)}
                    type="button"
                  >
                    <SidebarFigmaIcon name="sidebar-ellipsis" />
                  </button>
                </div>

                {menuOpen ? (
                  <ProjectSidebarActionsMenu
                    onArchive={() => controller.archiveProjectChats(project.id)}
                    onEdit={controller.projectRenameAvailable
                      ? () => controller.beginEditProject(project.id)
                      : undefined}
                    onNewChat={() => controller.createConversation(project.id)}
                    onTogglePinned={() => controller.togglePinned(project.id)}
                    project={project}
                  />
                ) : null}
              </div>

              {project.expanded ? (
                <div className={styles.conversationList}>
                  {project.conversations.length ? (
                    project.conversations.map((conversation) => {
                      const active =
                        controller.activePathname === pathnameOf(conversation.href);

                      return (
                        <Link
                          aria-current={active ? "page" : undefined}
                          className={`${styles.conversationRow} ${active ? styles.conversationRowActive : ""}`}
                          href={conversation.href}
                          key={conversation.id}
                          onClick={controller.closeMenu}
                          prefetch={false}
                        >
                          <SidebarMarqueeLabel text={conversation.title} />
                          <SidebarConversationStatus status={conversation.status} />
                        </Link>
                      );
                    })
                  ) : (
                    <p className={styles.emptyChats}>No chats</p>
                  )}
                </div>
              ) : null}
            </div>
          );
        })}
      </nav>
    </section>
  );
}
