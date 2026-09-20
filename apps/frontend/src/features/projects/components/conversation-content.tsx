"use client";

import { useMemo } from "react";
import type { ProjectChatController } from "../hooks/use-project-chat-controller";
import type { ProjectEntity } from "../model/project-workspace";
import { useTranscriptAutoScroll } from "../hooks/use-transcript-auto-scroll";
import { openClarification } from "../model/clarification";
import { ChatTranscript } from "./chat-transcript";
import styles from "./project-flow.module.css";

/**
 * The conversation content, extracted from the retired ConversationPane so
 * the Phase C chat surface can slot it into the designed `.conversationStage`
 * (C-3). Everything the pane rendered survives except two deliberate
 * removals: the in-pane thread `<select>` + new-thread button (founder ruling
 * R4, 2026-08-17 — the sidebar owns thread switching) and the composer,
 * which moves to the design's composer dock.
 *
 * Three behaviours the fixture era did not have, and all three are
 * contractual:
 *
 * - **the composer stays usable during detached work** (§3.5). Research runs
 *   do not lock the thread, so the user keeps asking questions; a turn
 *   submitted while another is executing is *visibly queued* rather than
 *   silently dropped or raced.
 * - **Stop acts on the active generation attempt only** (§3.5). It does not
 *   roll back committed tool effects and does not suspend a detached run, and
 *   the control says so by appearing only for the exactly-running turn.
 * - **access refusals are a state** (Lane B contract §6), never an empty
 *   transcript: a session that expired or a membership that changed says so.
 */
export function ConversationContent({
  chat,
  contextEntities,
  contextHandoffError,
  onOpenPlan,
}: {
  chat: ProjectChatController;
  /** The composer's whole catalog, so a chip resolves whatever was mentioned. */
  contextEntities: ProjectEntity[];
  contextHandoffError: string | null;
  onOpenPlan?: (documentId: string) => void;
}) {
  const activeUserMessageId = chat.transcript.reduce<string | null>(
    (latest, message) => (message.role === "user" ? message.id : latest),
    null,
  );
  const { transcriptScrollRef } = useTranscriptAutoScroll({
    activeMessageRevision: activeUserMessageId,
    // C5 scrollback: reaching the top of the list loads the preceding durable
    // page; the hook re-anchors the view when it prepends. No new UI — the
    // dummy build shows nothing during a scrollback fetch, so nothing renders.
    canLoadOlder: chat.hasOlderMessages,
    onLoadOlder: () => void chat.loadOlderMessages(),
    revision: chat.transcript.reduce(
      (total, message) => total + message.parts.length + (message.body ? 1 : 0),
      chat.transcript.length,
    ),
  });

  // The asking turn's questions are shown ONCE. While the interactive card is
  // up above the composer, that turn's inline read-only record would be the
  // same questions a second time; older asking turns keep theirs.
  const openClarificationTurnId = useMemo(
    () => openClarification(chat.transcript)?.turnId ?? null,
    [chat.transcript],
  );

  const partActions = useMemo(
    () => ({
      busy: chat.submitting,
      onOpenPlan,
      openClarificationTurnId,
      gateFor: chat.gateFor,
      onGateDecision: (
        card: Parameters<ProjectChatController["answerGate"]>[0],
        input: Parameters<ProjectChatController["answerGate"]>[1],
      ) => {
        void chat.answerGate(card, input);
      },
      onGateRecovery: (card: Parameters<ProjectChatController["recoverGate"]>[0]) => {
        void chat.recoverGate(card);
      },
    }),
    [chat, onOpenPlan, openClarificationTurnId],
  );

  return (
    <>
      {chat.access ? (
        <p className={styles.messageText} role="alert">
          {chat.access.message}
        </p>
      ) : null}
      {chat.route ? (
        <p className={styles.messageText} role="alert">
          {chat.route.message}
        </p>
      ) : null}
      {chat.error ? (
        <p className={styles.messageText} role="alert">
          {chat.error}
        </p>
      ) : null}
      {contextHandoffError ? (
        <p className={styles.messageText} role="alert">
          {contextHandoffError}
        </p>
      ) : null}
      <div className={styles.transcriptScroll} ref={transcriptScrollRef}>
        <ChatTranscript
          activeUserMessageId={activeUserMessageId}
          actions={partActions}
          contextEntities={contextEntities}
          gateAnswerForTurn={chat.gateAnswerForTurn}
          messages={chat.transcript}
        />
      </div>
    </>
  );
}
