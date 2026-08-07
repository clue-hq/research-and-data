import {
  Plan,
  PlanAction,
  PlanContent,
  PlanDescription,
  PlanHeader,
  PlanTitle,
  PlanTrigger,
} from "@/components/ai-elements/plan";
import type { ProjectWorkspace } from "../model/project-workspace";
import { ProjectIcon } from "./project-icon";
import styles from "./project-flow.module.css";

export function ProjectPlanSummary({
  onOpen,
  workspace,
}: {
  onOpen: () => void;
  workspace: ProjectWorkspace;
}) {
  return (
    <Plan className={styles.planSummary} defaultOpen={false}>
      <PlanHeader className={styles.planSummaryHeader}>
        <span className={styles.planSummaryIcon}><ProjectIcon name="list" size={15} /></span>
        <span>
          <PlanTitle className={styles.planSummaryTitle}>
            {workspace.conversationCopy.planCardLabel}
          </PlanTitle>
          <PlanDescription className={styles.planSummaryDescription}>
            {workspace.plan.title}
          </PlanDescription>
        </span>
        <PlanAction>
          <PlanTrigger className={styles.planSummaryTrigger}>
            <ProjectIcon className={styles.reasoningChevron} name="chevron-down" size={11} />
            <span className="sr-only">Toggle plan</span>
          </PlanTrigger>
        </PlanAction>
      </PlanHeader>
      <PlanContent className={styles.planSummaryContent}>
        <ol>
          {workspace.plan.sections.map((section) => (
            <li key={section.title}>
              <strong>{section.title}</strong>
              <span>{section.lines[0]}</span>
            </li>
          ))}
        </ol>
        <button onClick={onOpen} type="button">
          Open full plan <ProjectIcon name="chevron-right" size={8} />
        </button>
      </PlanContent>
    </Plan>
  );
}
