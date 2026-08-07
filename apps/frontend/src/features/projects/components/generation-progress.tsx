import { Shimmer } from "@/components/ai-elements/shimmer";
import {
  Task,
  TaskContent,
  TaskItem,
  TaskTrigger,
} from "@/components/ai-elements/task";
import Image from "next/image";
import type { GenerationStep, ProjectWorkspace } from "../model/project-workspace";
import { ProjectIcon } from "./project-icon";
import styles from "./project-flow.module.css";

export function GenerationProgress({
  complete,
  copy,
  onToggle,
  open,
  progress,
  steps,
}: {
  complete: boolean;
  copy: ProjectWorkspace["generationCopy"];
  onToggle: () => void;
  open: boolean;
  progress: number;
  steps: GenerationStep[];
}) {
  const title = complete ? copy.completeTimingLabel : copy.progressLabel;

  return (
    <Task className={styles.generationBlock} onOpenChange={onToggle} open={open}>
      <TaskTrigger className={styles.generationTrigger} title={title}>
        <ProjectIcon
          className={complete ? styles.statusCheck : styles.rotatingLoader}
          name={complete ? "status-check" : "loader"}
          size={complete ? 14 : 13}
        />
        {complete ? <span>{title}</span> : <Shimmer duration={1.4}>{title}</Shimmer>}
        <ProjectIcon className={styles.reasoningChevron} name="chevron-down" size={11} />
      </TaskTrigger>
      <TaskContent className={styles.generationTaskContent}>
        {steps.map((step, index) => {
          const localProgress = complete
            ? 100
            : Math.max(0, Math.min(100, progress - index * 24));
          const stepComplete = complete || localProgress >= 100;
          return (
            <TaskItem className={styles.generationStep} key={step.id}>
              <span>
                <Image alt="" height={14} src={step.logoPath} width={14} />
                <strong>{step.label}</strong>
                {stepComplete ? (
                  <ProjectIcon className={styles.statusCheck} name="status-check" size={13} />
                ) : null}
              </span>
              <small>{stepComplete ? "Complete" : step.note}</small>
              {!complete ? (
                <i
                  aria-label={`${step.label} ${localProgress}% complete`}
                  aria-valuemax={100}
                  aria-valuemin={0}
                  aria-valuenow={localProgress}
                  role="progressbar"
                >
                  <b style={{ width: `${localProgress}%` }} />
                </i>
              ) : null}
            </TaskItem>
          );
        })}
        <p>{complete ? copy.completeCreditsLabel : copy.progressCreditsLabel}</p>
      </TaskContent>
    </Task>
  );
}
