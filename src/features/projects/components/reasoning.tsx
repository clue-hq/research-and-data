import {
  Reasoning as AiReasoning,
  ReasoningContent,
  ReasoningTrigger,
} from "@/components/ai-elements/reasoning";
import { Shimmer } from "@/components/ai-elements/shimmer";
import type { ReactNode } from "react";
import { ProjectIcon } from "./project-icon";
import styles from "./project-flow.module.css";

export function Reasoning({
  children,
  expandable = true,
  label,
  onToggle,
  open,
  streaming = false,
}: {
  children?: ReactNode;
  expandable?: boolean;
  label?: string;
  onToggle?: (open: boolean) => void;
  open?: boolean;
  streaming?: boolean;
}) {
  const resolvedLabel = label ?? (streaming ? "Thinking" : "Thought for 5 seconds");

  if (!expandable) {
    return (
      <div
        aria-live={streaming ? "polite" : undefined}
        className={`${styles.reasoningTrigger} ${styles.reasoningStatus}`}
        role={streaming ? "status" : undefined}
      >
        {streaming ? (
          <ProjectIcon className={styles.rotatingLoader} name="loader" size={13} />
        ) : null}
        {streaming ? (
          <Shimmer duration={1.8}>{resolvedLabel}</Shimmer>
        ) : (
          <span>{resolvedLabel}</span>
        )}
      </div>
    );
  }

  return (
    <AiReasoning
      className={styles.reasoning}
      duration={streaming ? undefined : 5}
      isStreaming={streaming}
      onOpenChange={onToggle}
      defaultOpen={streaming}
      open={open}
    >
      <ReasoningTrigger className={styles.reasoningTrigger}>
        {streaming ? (
          <ProjectIcon className={styles.rotatingLoader} name="loader" size={13} />
        ) : null}
        {streaming ? (
          <Shimmer duration={1.8}>{resolvedLabel}</Shimmer>
        ) : (
          <span>{resolvedLabel}</span>
        )}
        <ProjectIcon className={styles.reasoningChevron} name="chevron-down" size={12} />
      </ReasoningTrigger>
      {children ? (
        <ReasoningContent className={styles.reasoningContent}>{children}</ReasoningContent>
      ) : null}
    </AiReasoning>
  );
}
