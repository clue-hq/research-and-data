import { Shimmer } from "@/components/ai-elements/shimmer";
import {
  Task,
  TaskContent,
  TaskItem,
  TaskTrigger,
} from "@/components/ai-elements/task";
import type { ChatTaskPart } from "../model/chat-parts";
import {
  RESEARCH_PHASES,
  researchActivityLabel,
  researchTaskModel,
} from "../model/research-task";
import { ProjectIcon } from "./project-icon";
import styles from "./project-flow.module.css";

/**
 * The research-execution task — Figma `136:2`, charter §3.1's `task` row.
 *
 * **One run is one visible task at one account or five hundred.** Scale changes
 * the counts and the expandable detail; it never changes the hierarchy, so
 * there is no per-account card and no worker transcript here.
 *
 * The eight designed activity states plus the three terminal ones all render,
 * including the two recovery states the Figma flow calls out — `partial`
 * ("partial results preserved") and `needs_input` ("requests the smallest
 * required user action") — and `suspended`, which is a supervised pause and not
 * a failure.
 *
 * Progression is strictly event-driven: every value below comes from the task
 * part's own snapshot. Nothing in this component reads a clock, and the only
 * animation is the loader/shimmer, switched on by `running`.
 */
export function ChatResearchTask({
  onOpenChange,
  open,
  part,
}: {
  onOpenChange?: (open: boolean) => void;
  open?: boolean;
  part: ChatTaskPart;
}) {
  const task = researchTaskModel(part);
  const rail =
    task.phaseIndex === null ? RESEARCH_PHASES.length : task.phaseIndex + 1;

  return (
    <Task
      className={styles.generationBlock}
      data-activity={task.activity}
      onOpenChange={onOpenChange}
      open={open}
    >
      <TaskTrigger className={styles.generationTrigger} title={task.label}>
        <ProjectIcon
          className={task.running ? styles.rotatingLoader : styles.statusCheck}
          name={
            task.running
              ? "loader"
              : task.blocked
                ? "clipboard-list"
                : task.activity === "failed"
                  ? "close"
                  : "status-check"
          }
          size={task.running ? 13 : 14}
        />
        {task.running ? (
          <Shimmer duration={1.4}>{task.label}</Shimmer>
        ) : (
          <span>{task.label}</span>
        )}
        <small>{task.summary}</small>
        <ProjectIcon className={styles.reasoningChevron} name="chevron-down" size={11} />
      </TaskTrigger>
      <TaskContent className={styles.generationTaskContent}>
        <TaskItem className={styles.generationStep}>
          <span>
            <strong>{task.title}</strong>
          </span>
          <small>
            {task.total === 1
              ? "1 account"
              : `${task.total} accounts, aggregated behind one task`}
          </small>
          <i
            aria-label={`${researchActivityLabel(task.activity)} — phase ${rail} of ${RESEARCH_PHASES.length}`}
            aria-valuemax={RESEARCH_PHASES.length}
            aria-valuemin={0}
            aria-valuenow={rail}
            role="progressbar"
          >
            <b style={{ width: `${(rail / RESEARCH_PHASES.length) * 100}%` }} />
          </i>
        </TaskItem>
        {task.steps.map((step) => (
          <TaskItem className={styles.generationStep} data-tone={step.tone} key={step.id}>
            <span>
              <strong>{step.label}</strong>
            </span>
            <small>
              {step.count} {step.count === 1 ? "account" : "accounts"}
            </small>
          </TaskItem>
        ))}
        {task.exceptionCount > 0 ? (
          <p>
            {task.exceptionCount === 1
              ? "1 exception isolated — the rest of the run is unaffected"
              : `${task.exceptionCount} exceptions isolated — the rest of the run is unaffected`}
          </p>
        ) : null}
      </TaskContent>
    </Task>
  );
}
