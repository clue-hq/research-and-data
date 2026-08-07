import type { ProjectMessage, ProjectWorkspace } from "../model/project-workspace";
import { ProjectIcon } from "./project-icon";
import { ProjectMessagePartView } from "./project-message-part";
import styles from "./project-flow.module.css";

export function ProjectMessageTimeline({
  controller,
  messages,
  workspace,
}: {
  controller: ReturnType<typeof import("../hooks/use-project-workspace-controller").useProjectWorkspaceController>;
  messages: ProjectMessage[];
  workspace: ProjectWorkspace;
}) {
  const actions = {
    openPlan: controller.openPlan,
    openQuestionnaire: controller.openQuestionnaire,
    setChainOpen: controller.setChainOpen,
    setGenerationDetailsOpen: controller.setGenerationDetailsOpen,
  };

  return (
    <div className={styles.transcript} role="log">
      {messages.map((message) => (
        <article
          className={styles.projectMessage}
          data-role={message.role}
          key={message.id}
        >
          {message.authorLabel ? (
            <div className={styles.assistantAttribution}>
              <ProjectIcon name="clue" size={13} />
              {message.authorLabel}
            </div>
          ) : null}
          <div className={styles.messageParts}>
            {message.parts.map((part) => (
              <ProjectMessagePartView
                actions={actions}
                chainOpen={controller.chainOpen}
                generationDetailsOpen={controller.generationDetailsOpen}
                key={part.id}
                part={part}
                workspace={workspace}
              />
            ))}
          </div>
        </article>
      ))}
    </div>
  );
}
