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
  return (
    <main className={styles.projectWorkspace} data-phase={controller.previewSurface}>
      <header className={styles.projectHeader}>
        <div>
          <button aria-label="Go to home" onClick={controller.openHome} type="button"><ProjectIcon name="menu" size={16} /></button>
          <button className={styles.projectTitle} type="button">{workspace.title}<ProjectIcon name="chevron-down" size={12} /></button>
        </div>
        <button aria-label="Copy project link" onClick={onCopyLink} type="button"><ProjectIcon name="link" size={14} /></button>
      </header>
      <div className={styles.projectColumns} data-focus={controller.focusPane}>
        <ConversationPane chat={chat} controller={controller} workspace={workspace} />
        <ArtifactWorkspace controller={controller} workspace={workspace} />
      </div>
    </main>
  );
}
