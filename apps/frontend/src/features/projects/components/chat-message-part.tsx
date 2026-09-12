"use client";

import {
  Plan,
  PlanContent,
  PlanDescription,
  PlanHeader,
  PlanTitle,
  PlanTrigger,
} from "@/components/ai-elements/plan";
import {
  Source,
  Sources,
  SourcesContent,
  SourcesTrigger,
} from "@/components/ai-elements/sources";
import { MessageResponse } from "@/components/ai-elements/message-response";
import type { ChatGatePart, ChatPart } from "../model/chat-parts";
import type { GateCardModel, GateDecisionInput } from "../model/chat-gate";
import { ChatGateCard } from "./chat-gate-card";
import { ChatResearchTask } from "./chat-research-task";
import { ChatToolCall } from "./chat-tool-call";
import { ProjectIcon } from "./project-icon";
import styles from "./project-flow.module.css";

/**
 * The §3.1 map, in one switch: a Clue domain part in, a vendored primitive out.
 *
 * There is exactly one of these, and no component below it ever sees an event,
 * a repository, or a transport. Adding a part kind means adding a row here and
 * a renderer beside it — never a branch inside a presentation component.
 */
export interface ChatPartActions {
  busy: boolean;
  gateFor(part: ChatGatePart): GateCardModel | null;
  onGateDecision(
    card: GateCardModel,
    input: GateDecisionInput,
  ): void;
  onGateRecovery(card: GateCardModel): void;
}

export function ChatMessagePartView({
  actions,
  part,
}: {
  actions: ChatPartActions;
  part: ChatPart;
}) {
  switch (part.kind) {
    case "text":
      return (
        <div className={styles.messageText} data-streaming={part.streaming || undefined}>
          <MessageResponse streaming={part.streaming}>{part.text}</MessageResponse>
          {part.failed && part.failureReason !== "stop_requested" ? (
            <p role="note">
              <ProjectIcon name="close" size={12} />
              {part.failureReason
                ? `Response interrupted: ${part.failureReason}`
                : "This response could not finish"}
            </p>
          ) : null}
        </div>
      );
    case "reasoning":
    case "agent_activity":
      // Reasoning is consolidated at the message level. Activity receipts stay
      // in the stream/inspector, without duplicating the same rounds in chat.
      return null;
    case "tool":
      return <ChatToolCall part={part} />;
    case "task":
      return <ChatResearchTask part={part} />;
    case "plan":
      return (
        <Plan className={styles.planSummary} defaultOpen={false}>
          <PlanHeader>
            <PlanTitle>{part.title}</PlanTitle>
            {part.revisionLabel ? (
              <PlanDescription>{`Revision ${part.revisionLabel}`}</PlanDescription>
            ) : null}
            <PlanTrigger />
          </PlanHeader>
          <PlanContent>
            {part.summary ? <p className={styles.messageText}>{part.summary}</p> : null}
            <ol className={styles.planSummaryContent}>
              {part.steps.map((step) => (
                <li data-status={step.status} key={step.id}>
                  {step.label}
                </li>
              ))}
            </ol>
          </PlanContent>
        </Plan>
      );
    case "gate": {
      const card = actions.gateFor(part);
      if (!card) return null;
      return (
        <ChatGateCard
          busy={actions.busy}
          card={card}
          onDecide={actions.onGateDecision}
          onRecover={actions.onGateRecovery}
        />
      );
    }
    case "sources":
      return (
        <Sources className={styles.projectSources} defaultOpen={false}>
          <SourcesTrigger
            className={styles.projectSourcesTrigger}
            count={part.items.length}
          >
            <ProjectIcon name="link" size={12} />
            <span>
              {part.items.length === 1 ? "1 source" : `${part.items.length} sources`}
            </span>
            <ProjectIcon
              className={styles.reasoningChevron}
              name="chevron-down"
              size={11}
            />
          </SourcesTrigger>
          <SourcesContent className={styles.projectSourcesContent}>
            {part.items.map((item, index) => {
              const label = item.title?.trim() || `Source ${index + 1}`;
              return (
                <Source
                  href={item.url ?? undefined}
                  key={item.sourceId}
                  title={label}
                >
                  <span>{label}</span>
                  {item.url ? <ProjectIcon name="link" size={10} /> : null}
                </Source>
              );
            })}
          </SourcesContent>
        </Sources>
      );
  }
}
