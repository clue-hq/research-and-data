import type { ProjectMessagePart, ProjectWorkspace } from "../model/project-workspace";
import { ChainOfThought } from "./chain-of-thought";
import { GenerationProgress } from "./generation-progress";
import { ProjectIcon } from "./project-icon";
import { ProjectPlanSummary } from "./project-plan-summary";
import { ProjectSources } from "./project-sources";
import { ProjectToolActivity } from "./project-tool-activity";
import { Reasoning } from "./reasoning";
import styles from "./project-flow.module.css";

interface ProjectMessagePartActions {
  openPlan: () => void;
  openQuestionnaire: () => void;
  setChainOpen: (open: boolean) => void;
  setGenerationDetailsOpen: (open: boolean) => void;
}

export function ProjectMessagePartView({
  actions,
  chainOpen,
  generationDetailsOpen,
  part,
  workspace,
}: {
  actions: ProjectMessagePartActions;
  chainOpen: boolean;
  generationDetailsOpen: boolean;
  part: ProjectMessagePart;
  workspace: ProjectWorkspace;
}) {
  switch (part.type) {
    case "text":
      return <p className={styles.messageText}>{part.text}</p>;
    case "reasoning":
      return (
        <Reasoning
          expandable={Boolean(part.detail || part.showTrace)}
          label={part.label}
          streaming={part.streaming}
        >
          {part.detail ? <p>{part.detail}</p> : null}
          {part.showTrace ? (
            <ChainOfThought
              data={workspace.reasoningTrace}
              onToggle={() => actions.setChainOpen(!chainOpen)}
              open={chainOpen}
            />
          ) : null}
        </Reasoning>
      );
    case "action":
      return (
        <button
          className={styles.transcriptCard}
          onClick={part.action === "plan" ? actions.openPlan : actions.openQuestionnaire}
          type="button"
        >
          <ProjectIcon name={part.icon} size={15} />
          {part.label}
          <ProjectIcon name="chevron-right" size={8} />
        </button>
      );
    case "tool":
      return <ProjectToolActivity part={part} />;
    case "plan":
      return <ProjectPlanSummary onOpen={actions.openPlan} workspace={workspace} />;
    case "task":
      return (
        <GenerationProgress
          complete={part.complete}
          copy={workspace.generationCopy}
          onToggle={() => actions.setGenerationDetailsOpen(!generationDetailsOpen)}
          open={generationDetailsOpen}
          progress={part.progress}
          steps={workspace.generationSteps}
        />
      );
    case "sources":
      return <ProjectSources sources={workspace.conversationActivity.sources} />;
  }
}
