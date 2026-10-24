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
import { ClarificationHistoryCard } from "@/features/chat-shell/components/clarification-card";
import type { ChatGatePart, ChatPart } from "../model/chat-parts";
import type { GateCardModel, GateDecisionInput } from "../model/chat-gate";
import { crmConnectCard, type CrmProvider } from "@/features/integrations/model/crm";
import { ChatGateCard } from "./chat-gate-card";
import { CrmConnectCard } from "./crm-connect-card";
import { CrmWritePermissionCard } from "./crm-write-permission-card";
import { ChatResearchTask } from "./chat-research-task";
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
  /** The turn whose clarification parts the card above the composer is showing; its inline record is suppressed. */
  openClarificationTurnId?: string | null;
  onOpenPlan?: (documentId: string) => void;
  gateFor(part: ChatGatePart): GateCardModel | null;
  onGateDecision(
    card: GateCardModel,
    input: GateDecisionInput,
  ): void;
  onGateRecovery(card: GateCardModel): void;
  /** Send a plain chat message (e.g. the CRM card's "I'll give the numbers myself"). */
  onSendMessage?: (message: string) => void;
  /** The thread's count of "changes finished" wake-up turns; a CRM write card re-reads when it moves. */
  crmWritesFinished?: number;
  /** The CRM connect card's action: a fresh login link (R-3.10). */
  onCrmConnect?: (requestId: string, provider: CrmProvider) => Promise<string>;
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
    case "tool": {
      // Tool receipts remain in the event history, but per-step activity rows
      // are not part of the chat UI (release cleanup, 2026-09-20). The one
      // exception is a finished `connect_crm` call that asked for a connect
      // card (CRM integration, R-3.10): the card IS that tool's result.
      if (part.toolName !== "connect_crm" || part.state !== "output-available") return null;
      const card = crmConnectCard(part.output);
      return card ? <CrmConnectCard
          card={card}
          onConnect={actions.onCrmConnect}
          onSendMessage={actions.onSendMessage}
        /> : null;
    }
    case "task":
      return <ChatResearchTask part={part} />;
    case "plan":
      return (
        <Plan className={styles.planSummary} defaultOpen={false}>
          <PlanHeader>
            {part.planRef?.objectType === "project_document" && part.planRef.objectId && actions.onOpenPlan ? (
              <button type="button" className={`${styles.planSummaryTitle} ${styles.planDocumentLink}`} onClick={() => { if (part.planRef.objectId) actions.onOpenPlan?.(part.planRef.objectId); }}>
                {part.title}<ProjectIcon name="chevron-right" size={12} />
              </button>
            ) : <PlanTitle>{part.title}</PlanTitle>}
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
      // A CRM write permission card has its own frame; a notice about one (its gate could not be
      // read) stays the shared approval card's.
      if (card.crmWrite !== null) {
        return (
          <CrmWritePermissionCard
            busy={actions.busy}
            card={card}
            onDecide={actions.onGateDecision}
            wake={actions.crmWritesFinished ?? 0}
          />
        );
      }
      return (
        <ChatGateCard
          busy={actions.busy}
          card={card}
          onDecide={actions.onGateDecision}
          onRecover={actions.onGateRecovery}
        />
      );
    }
    case "clarification":
      // The interactive card lives above the composer and is driven from the
      // transcript's LAST turn (`openClarification`). Here — inline, in the
      // message that asked — the part is a read-only record: the questions and
      // their defaults, and the fact that the answer is the next message.
      return <ClarificationHistoryCard part={part} />;
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
