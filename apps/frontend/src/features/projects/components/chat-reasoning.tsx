"use client";

import { useState } from "react";
import {
  Reasoning,
  ReasoningContent,
  ReasoningTrigger,
} from "@/components/ai-elements/reasoning";
import { Shimmer } from "@/components/ai-elements/shimmer";
import type { ChatPart } from "../model/chat-parts";
import { presentChatReasoning } from "../model/chat-reasoning-presentation";
import type { TranscriptTurnState } from "../model/chat-transcript";
import { ProjectIcon } from "./project-icon";
import styles from "./chat-reasoning.module.css";

/** Presentation only: trace availability and retention remain backend-owned. */
export function ChatReasoning({
  parts,
  turnState,
}: {
  parts: readonly ChatPart[];
  turnState: TranscriptTurnState;
}) {
  const trace = presentChatReasoning(parts, turnState);
  if (!trace.text) {
    // No empty disclosure or completed-step receipt when no trace was supplied.
    return trace.active ? (
      <div className={styles.status} role="status">
        <Shimmer className={styles.shimmer} duration={2.4}>Thinking…</Shimmer>
      </div>
    ) : null;
  }
  return <TraceDisclosure {...trace} />;
}

function TraceDisclosure({
  active,
  ephemeral,
  running,
  text,
}: ReturnType<typeof presentChatReasoning>) {
  const [open, setOpen] = useState(running);
  return (
    <Reasoning
      className={styles.trace}
      data-ephemeral={ephemeral || undefined}
      // Keep a user's collapse choice during streaming and between model rounds.
      defaultOpen={false}
      isStreaming={running}
      onOpenChange={setOpen}
      open={open}
    >
      <ReasoningTrigger
        aria-label={open ? "Collapse reasoning" : "Expand reasoning"}
        className={styles.trigger}
      >
        {active ? (
          <Shimmer className={styles.shimmer} duration={2.4}>Thinking…</Shimmer>
        ) : <span>Reasoning</span>}
        <ProjectIcon className={styles.chevron} name="chevron-down" size={14} />
      </ReasoningTrigger>
      <ReasoningContent className={styles.content}>
        <div
          aria-label="Reasoning text"
          className={styles.text}
          role="region"
          tabIndex={open ? 0 : -1}
        >
          {text}
        </div>
      </ReasoningContent>
    </Reasoning>
  );
}
