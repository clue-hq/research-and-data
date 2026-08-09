import { useApplicationSidebar } from "@/components/shell/application-shell";
import { PROJECT_SIDEBAR_TRIGGER_ID } from "@/components/shell/use-desktop-sidebar";
import type { ProjectChatController } from "../hooks/use-project-chat-controller";
import type { ProjectWorkspace } from "../model/project-workspace";
import { ArtifactWorkspace } from "./artifact-workspace";
import { ConversationPane } from "./conversation-pane";
import { ProjectIcon } from "./project-icon";
import styles from "./project-flow.module.css";

export function ProjectWorkspaceView({
  chat,
  controller,
  onCopyLink,
  workspace,
}: {
  chat: ProjectChatController;
  controller: ReturnType<typeof import("../hooks/use-project-workspace-controller").useProjectWorkspaceController>;
  onCopyLink: () => void;
  workspace: ProjectWorkspace;
}) {
  const sidebar = useApplicationSidebar();
  const pinned = sidebar.state === "pinned-expanded";
  return (
    <main className={styles.projectWorkspace}>
      <header className={styles.projectHeader}>
        <div>
          <button
            aria-controls="application-sidebar"
            aria-expanded={sidebar.expanded}
            aria-label={pinned ? "Collapse sidebar" : "Pin sidebar open"}
            className={styles.desktopSidebarTrigger}
            id={PROJECT_SIDEBAR_TRIGGER_ID}
            onBlur={sidebar.scheduleDismissal}
            onClick={(event) => sidebar.toggle(event.currentTarget)}
            onFocus={(event) => sidebar.preview(event.currentTarget)}
            onPointerEnter={(event) => sidebar.preview(event.currentTarget)}
            onPointerLeave={sidebar.scheduleDismissal}
            type="button"
          >
            <ProjectIcon name="menu" size={16} />
          </button>
          <button className={styles.projectTitle} type="button">{workspace.title}<ProjectIcon name="chevron-down" size={12} /></button>
        </div>
        <button aria-label="Copy project link" onClick={onCopyLink} type="button"><ProjectIcon name="link" size={14} /></button>
      </header>
      <div className={styles.projectColumns} data-focus={controller.focusPane}>
        <ConversationPane
          chat={chat}
          controller={controller}
          projectId={workspace.id}
          workspace={workspace}
        />
        <ArtifactWorkspace controller={controller} />
      </div>
    </main>
  );
}
