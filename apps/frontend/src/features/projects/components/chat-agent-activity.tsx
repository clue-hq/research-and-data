import {
  ChainOfThought,
  ChainOfThoughtContent,
  ChainOfThoughtHeader,
  ChainOfThoughtStep,
} from "@/components/ai-elements/chain-of-thought";
import { Shimmer } from "@/components/ai-elements/shimmer";
import type { ChatActivityPart, ChatReasoningPart } from "../model/chat-parts";
import type { ProjectIconName } from "../config/project-icon-sources";
import { ProjectIcon } from "./project-icon";
import styles from "./project-flow.module.css";

/**
 * The Clue adapters for the two safe agent-status surfaces.
 *
 * `ChainOfThought` here means what §3.1 says it means: **a structured summary
 * of steps the platform durably recorded** — a model round beginning, a
 * governed tool succeeding or being refused — and never private raw model
 * reasoning, which the backend does not send and this cannot render.
 *
 * `Shimmer` has no wire part. It is switched on by the part's own `active`
 * state, so the animation is derived from what is happening rather than from a
 * duration the backend guessed at.
 */

/** Semantic step kind → an approved Figma export. Unknown kinds fall back. */
const STEP_ICONS = {
  model_round: "sparkles",
  tool_call: "clipboard-list",
} as const satisfies Record<string, ProjectIconName>;

export function ChatAgentActivity({
  onOpenChange,
  open,
  part,
}: {
  onOpenChange?: (open: boolean) => void;
  open?: boolean;
  part: ChatActivityPart;
}) {
  if (part.steps.length === 0) return null;
  return (
    <ChainOfThought
      className={styles.chainOfThought}
      onOpenChange={onOpenChange}
      open={open}
    >
      <ChainOfThoughtHeader
        className={styles.chainHeader}
        icon={<></>}
        indicator={
          <ProjectIcon className={styles.reasoningChevron} name="chevron-down" size={12} />
        }
      >
        {part.title}
      </ChainOfThoughtHeader>
      <ChainOfThoughtContent className={styles.chainContent}>
        {part.steps.map((step) => (
          <ChainOfThoughtStep
            className={styles.traceStep}
            icon={
              <ProjectIcon
                className={step.status === "active" ? styles.rotatingLoader : undefined}
                name={
                  step.status === "active"
                    ? "loader"
                    : (STEP_ICONS[step.kind as keyof typeof STEP_ICONS] ?? "status-check")
                }
                size={14}
              />
            }
            key={step.id}
            label={step.label}
            status={
              step.status === "complete"
                ? "complete"
                : step.status === "active"
                  ? "active"
                  : "pending"
            }
          >
            {step.description ? (
              <p className={styles.traceDetail}>{step.description}</p>
            ) : null}
          </ChainOfThoughtStep>
        ))}
      </ChainOfThoughtContent>
    </ChainOfThought>
  );
}

/**
 * A model round's safe status line.
 *
 * The part carries no text at all — what the model privately "thought" is not a
 * platform output — so the copy is the adapter's, and there is no
 * backend-authored "Thought for 5 seconds" anywhere in this component.
 */
export function ChatReasoning({ part }: { part: ChatReasoningPart }) {
  const active = part.state === "active";
  const label = active
    ? "Thinking"
    : part.state === "error"
      ? "Round failed"
      : part.requestedToolCalls > 0
        ? `Planned ${part.requestedToolCalls} tool ${
            part.requestedToolCalls === 1 ? "call" : "calls"
          }`
        : "Round complete";

  return (
    <div
      aria-live={active ? "polite" : undefined}
      className={`${styles.reasoningTrigger} ${styles.reasoningStatus}`}
      role={active ? "status" : undefined}
    >
      {active ? (
        <ProjectIcon className={styles.rotatingLoader} name="loader" size={13} />
      ) : (
        <ProjectIcon className={styles.statusCheck} name="status-check" size={13} />
      )}
      {active ? <Shimmer duration={1.4}>{label}</Shimmer> : <span>{label}</span>}
    </div>
  );
}
