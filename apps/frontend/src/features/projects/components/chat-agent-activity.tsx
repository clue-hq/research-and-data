import {
  ChainOfThought,
  ChainOfThoughtContent,
  ChainOfThoughtHeader,
  ChainOfThoughtStep,
} from "@/components/ai-elements/chain-of-thought";
import {
  Reasoning,
  ReasoningContent,
  ReasoningTrigger,
} from "@/components/ai-elements/reasoning";
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

function reasoningLabel(part: ChatReasoningPart): string {
  if (part.state === "active") return "Thinking";
  if (part.state === "error") return "Round failed";
  if (part.requestedToolCalls > 0) {
    return `Planned ${part.requestedToolCalls} tool ${
      part.requestedToolCalls === 1 ? "call" : "calls"
    }`;
  }
  return "Round complete";
}

/**
 * A model round.
 *
 * In every production deployment the part carries no text — what the model
 * privately "thought" is not a platform output — and this renders the status
 * line it always has, with the copy chosen here rather than sent by the backend.
 *
 * When the **dev-only** raw-reasoning lens is configured the part additionally
 * carries a streamed trace, and the row becomes the vendored `Reasoning`
 * disclosure so the text can be read and collapsed. The switch is *payload
 * presence*, not a frontend flag: this component has no way to know what the
 * server is configured to send, and pretending otherwise would mean a client
 * env var and a server env var that could disagree. `isStreaming` is the part's
 * own `active` state, so the shimmer and the auto-open are derived from what is
 * happening rather than from a duration the backend guessed at.
 *
 * The trace is labelled as not-durable because it is not: `textEphemeral` says
 * so on the wire, and a reload will not bring it back.
 */
export function ChatReasoning({ part }: { part: ChatReasoningPart }) {
  const active = part.state === "active";
  const label = reasoningLabel(part);
  const status = (
    <>
      {active ? (
        <ProjectIcon className={styles.rotatingLoader} name="loader" size={13} />
      ) : (
        <ProjectIcon className={styles.statusCheck} name="status-check" size={13} />
      )}
      {active ? <Shimmer duration={1.4}>{label}</Shimmer> : <span>{label}</span>}
    </>
  );

  if (!part.text) {
    return (
      <div
        aria-live={active ? "polite" : undefined}
        className={`${styles.reasoningTrigger} ${styles.reasoningStatus}`}
        role={active ? "status" : undefined}
      >
        {status}
      </div>
    );
  }

  return (
    <Reasoning
      className={styles.reasoningTrace}
      data-ephemeral={part.textEphemeral || undefined}
      isStreaming={active}
    >
      <ReasoningTrigger
        className={`${styles.reasoningTrigger} ${styles.reasoningStatus}`}
        getThinkingMessage={() => status}
      />
      <ReasoningContent className={styles.reasoningTraceContent}>
        <p className={styles.reasoningTraceNote}>
          Raw model reasoning — development lens only, and not part of the saved
          conversation.
        </p>
        <pre className={styles.reasoningTraceText}>{part.text}</pre>
      </ReasoningContent>
    </Reasoning>
  );
}
