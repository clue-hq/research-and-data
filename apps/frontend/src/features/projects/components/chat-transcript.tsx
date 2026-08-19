"use client";

import { MessageResponse } from "@/components/ai-elements/message-response";
import { unavailableMessageBody } from "../model/chat-message";
import type { GateAnswerDisplay } from "../model/chat-gate";
import {
  gateResponseBodyDisplay,
  humanizeMessageBody,
} from "../model/chat-message-presentation";
import type { TranscriptMessage } from "../model/chat-transcript";
import {
  DESIGN_GENERATION_WAIT_NOTICE,
  designTurnFailureNotice,
} from "../model/design-leg";
import type { ProjectEntity } from "../model/project-workspace";
import { ChatMessagePartView, type ChatPartActions } from "./chat-message-part";
import { ProjectIcon } from "./project-icon";
import styles from "./project-flow.module.css";

/**
 * The transcript: durable messages and live projections, in one ordered log.
 *
 * Nothing here manufactures a message. Every entry came from a durable read, a
 * turn event, or the user's own submission a moment ago — which is the whole
 * difference between this component and the phase-enum transcript it replaces.
 */
export function ChatTranscript({
  activeUserMessageId = null,
  actions,
  assistantName = "Clue",
  contextEntities = [],
  gateAnswerForTurn,
  messages,
  onInspectTurn,
}: {
  activeUserMessageId?: string | null;
  actions: ChatPartActions;
  assistantName?: string;
  contextEntities?: readonly ProjectEntity[];
  gateAnswerForTurn?: (turnId: string) => GateAnswerDisplay | null;
  messages: readonly TranscriptMessage[];
  /**
   * The dev-lens affordance, or absent.
   *
   * `undefined` is the production shape and the default: the capability probe
   * 404s against any deployment that did not register the inspector routes, so
   * the caller passes nothing and no button is rendered. No component here reads
   * an environment variable to decide — a client flag could disagree with the
   * server's, and asking cannot.
   */
  onInspectTurn?: (turnId: string) => void;
}) {
  return (
    <div className={styles.transcript} role="log">
      {messages.map((message) => {
        const gateAnswer =
          message.role === "user"
            ? (gateAnswerForTurn?.(message.turnId) ??
              gateResponseBodyDisplay(message.body))
            : null;
        const displayBody =
          gateAnswer === null && message.body !== null
            ? humanizeMessageBody(message.body)
            : null;

        return (
          <article
          className={styles.projectMessage}
          data-active-message={
            message.id === activeUserMessageId ? "true" : undefined
          }
          data-optimistic={message.optimistic || undefined}
          data-role={message.role}
          data-state={message.state}
          key={message.id}
        >
          {message.role === "assistant" ? (
            <div className={styles.assistantAttribution}>
              <ProjectIcon name="clue" size={13} />
              {assistantName}
              {onInspectTurn && !message.optimistic ? (
                <button
                  aria-label="Inspect response details"
                  className={styles.turnLensTrigger}
                  onClick={() => onInspectTurn(message.turnId)}
                  type="button"
                >
                  Inspect
                </button>
              ) : null}
            </div>
          ) : null}
          <div className={styles.messageParts}>
            {message.refs.some((ref) => ref.flavor === "context") ? (
              <div aria-label="Message context" className={styles.messageContextRefs}>
                {message.refs
                  .filter((ref) => ref.flavor === "context")
                  .sort((left, right) => left.ordinal - right.ordinal)
                  .map((ref) => {
                    const entity = contextEntities.find(
                      (candidate) =>
                        candidate.id === ref.objectId &&
                        candidate.type === ref.objectType,
                    );
                    const fallbackLabel =
                      ref.objectType === "contact"
                        ? "Selected contact"
                        : "Selected account";
                    return (
                      <span key={`${ref.ordinal}:${ref.objectType}:${ref.objectId}`}>
                        @{entity?.label ?? fallbackLabel}
                      </span>
                    );
                  })}
              </div>
            ) : null}
            {gateAnswer !== null ? (
              <div className={styles.gateAnswerReceipt} role="status">
                <ProjectIcon name="status-check" size={14} />
                <span>{gateAnswer.label}</span>
                {gateAnswer.detail !== null ? (
                  <small>{`Requested changes: ${gateAnswer.detail}`}</small>
                ) : null}
              </div>
            ) : null}
            {displayBody !== null ? (
              <div className={styles.messageText}>
                <MessageResponse>{displayBody}</MessageResponse>
              </div>
            ) : null}
            {gateAnswer === null &&
            message.body === null &&
            message.bodyUnavailableReason ? (
              // An erased, oversized, or non-text body is reported. An empty
              // string here would render as a message nobody wrote.
              <p className={styles.messageText} role="note">
                {unavailableMessageBody(message.bodyUnavailableReason)}
              </p>
            ) : null}
            {message.parts.map((part) => (
              <ChatMessagePartView
                actions={actions}
                key={part.partId}
                part={part}
                turnState={message.state}
              />
            ))}
            {message.role === "assistant" &&
            message.state === "queued" &&
            message.parts.length === 0 ? (
              // The assistant owes an answer and no worker has claimed the turn
              // yet. A queued turn is visible because the submissions union
              // makes it visible — it is never silently dropped.
              <p className={styles.reasoningStatus} role="status">
                Queued
              </p>
            ) : null}
            {message.role === "assistant" &&
            message.state === "cancelled" &&
            message.body === null &&
            !message.parts.some(
              (part) =>
                part.kind === "reasoning" ||
                (part.kind === "text" && part.failed),
            ) ? (
              <p className={styles.reasoningStatus} role="status">
                Stopped
              </p>
            ) : null}
            {message.role === "assistant" &&
            message.state === "failed" &&
            message.body === null &&
            // A typed failure now renders its own sentence below, so the
            // generic placeholder would only say the same thing worse. It
            // exists for the failures that carry no code at all.
            message.failureCode === null &&
            !message.parts.some(
              (part) =>
                part.kind === "reasoning" ||
                (part.kind === "text" && part.failed),
            ) ? (
              <p className={styles.reasoningStatus} role="status">
                Response failed
              </p>
            ) : null}
            {message.generatingDesign ? (
              // Genweb slice 3, founder requirements 4 + 5: the one honest
              // thing this surface knows about a running design turn. No
              // percentage, no ETA, no progress bar — none of those would be
              // derived from anything.
              <p className={styles.reasoningStatus} role="status">
                {DESIGN_GENERATION_WAIT_NOTICE}
              </p>
            ) : null}
            {message.failureCode ? (
              // Requirement 7: a typed leg refusal renders as a sentence. An
              // unrecognized code still renders as itself — true, if terse —
              // rather than as an invented explanation.
              //
              // Above the leg lines on purpose: a failed design turn still
              // emits `leg.awaiting_user` (the leg genuinely came back), and
              // "what happened" has to be read before "what now".
              <p className={styles.messageText} role="note">
                {designTurnFailureNotice(message.failureCode)}
              </p>
            ) : null}
            {message.legNotices.map((notice, index) => (
              // The design leg's durable lifecycle, in the transcript's own
              // status-line pattern — the same element the queue and Stop
              // receipts use. No new component, and no speaker chip.
              <p
                className={styles.reasoningStatus}
                key={`${index}:${notice}`}
                role="status"
              >
                {notice}
              </p>
            ))}
          </div>
          </article>
        );
      })}
    </div>
  );
}
