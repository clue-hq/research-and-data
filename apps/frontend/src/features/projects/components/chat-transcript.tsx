"use client";

import { MessageResponse } from "@/components/ai-elements/message-response";
import type { TranscriptMessage } from "../model/chat-transcript";
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
  actions,
  assistantName = "Clue",
  messages,
}: {
  actions: ChatPartActions;
  assistantName?: string;
  messages: readonly TranscriptMessage[];
}) {
  return (
    <div className={styles.transcript} role="log">
      {messages.map((message) => (
        <article
          className={styles.projectMessage}
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
            {message.body !== null ? (
              <div className={styles.messageText}>
                <MessageResponse>{message.body}</MessageResponse>
              </div>
            ) : null}
            {message.body === null && message.bodyUnavailableReason ? (
              // An erased, oversized, or non-text body is reported. An empty
              // string here would render as a message nobody wrote.
              <p className={styles.messageText} role="note">
                This message&rsquo;s text is unavailable (
                {message.bodyUnavailableReason}).
              </p>
            ) : null}
            {message.parts.map((part) => (
              <ChatMessagePartView actions={actions} key={part.partId} part={part} />
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
            {message.failureCode ? (
              <p className={styles.messageText} role="note">
                {message.failureCode}
              </p>
            ) : null}
          </div>
        </article>
      ))}
    </div>
  );
}
