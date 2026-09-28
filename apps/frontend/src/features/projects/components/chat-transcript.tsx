"use client";

import { Attachments } from "@/components/ai-elements/attachments";
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
import { ChatReasoning } from "./chat-reasoning";
import { ChatMessageReference } from "./chat-message-reference";
import { ProjectIcon } from "./project-icon";
import styles from "./project-flow.module.css";

/**
 * The parts a message actually renders inline.
 *
 * One rule, and only one: the turn whose questions the clarification card is
 * asking right now does not ALSO print them read-only in its own bubble (spec
 * 2026-09-20 §2.5 scopes the inline record to turns that are not the latest).
 * Every other part of every other turn is rendered exactly as it arrived.
 */
function visibleParts(
  message: TranscriptMessage,
  actions: ChatPartActions,
): readonly TranscriptMessage["parts"][number][] {
  if (!actions.openClarificationTurnId) return message.parts;
  if (message.turnId !== actions.openClarificationTurnId) return message.parts;
  return message.parts.filter((part) => part.kind !== "clarification");
}

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
}: {
  activeUserMessageId?: string | null;
  actions: ChatPartActions;
  assistantName?: string;
  contextEntities?: readonly ProjectEntity[];
  gateAnswerForTurn?: (turnId: string) => GateAnswerDisplay | null;
  messages: readonly TranscriptMessage[];
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
          // The scrollback anchor (C5): re-anchoring after an older page
          // prepends needs each message findable by its durable identity.
          data-message-id={message.id}
          data-optimistic={message.optimistic || undefined}
          data-role={message.role}
          data-state={message.state}
          key={message.id}
        >
          {message.role === "assistant" ? (
            <div className={styles.assistantAttribution}>
              <ProjectIcon name="clue" size={13} />
              {assistantName}
            </div>
          ) : null}
          <div className={styles.messageParts}>
            {message.refs.some(
              (ref) => ref.flavor === "context" || ref.flavor === "attachment",
            ) ? (
              <Attachments aria-label="Message context" className={styles.messageContextRefs} variant="inline">
                {message.refs
                  .filter(
                    (ref) =>
                      ref.flavor === "context" || ref.flavor === "attachment",
                  )
                  .sort((left, right) => left.ordinal - right.ordinal)
                  .map((ref) => (
                    <ChatMessageReference
                      entity={contextEntities.find(
                        (candidate) => candidate.id === ref.objectId && candidate.type === ref.objectType,
                      )}
                      key={`${ref.ordinal}:${ref.flavor}:${ref.objectType}:${ref.objectId}`}
                      reference={ref}
                    />
                  ))}
              </Attachments>
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
            {message.role === "assistant" ? (
              <ChatReasoning parts={message.parts} turnState={message.state} />
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
            {visibleParts(message, actions).map((part) => (
              <ChatMessagePartView
                actions={actions}
                key={part.partId}
                part={part}
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
            message.state === "failed" &&
            message.body === null &&
            // A typed failure now renders its own sentence below, so the
            // generic placeholder would only say the same thing worse. It
            // exists for the failures that carry no code at all.
            message.failureCode === null &&
            !message.parts.some(
              (part) =>
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
