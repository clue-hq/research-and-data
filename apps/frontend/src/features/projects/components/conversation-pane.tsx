"use client";

import { useMemo } from "react";
import type { ProjectChatController } from "../hooks/use-project-chat-controller";
import type { ProjectWorkspace } from "../model/project-workspace";
import { useTranscriptAutoScroll } from "../hooks/use-transcript-auto-scroll";
import { useTurnInspector } from "../hooks/use-turn-inspector";
import { ChatTranscript } from "./chat-transcript";
import { ChatTurnInspector } from "./chat-turn-inspector";
import { ProjectComposer } from "./project-composer";
import { ProjectIcon } from "./project-icon";
import styles from "./project-flow.module.css";

/**
 * The conversation half of the project workspace, now backed by real turns.
 *
 * Three behaviours the fixture era did not have, and all three are contractual:
 *
 * - **the composer stays usable during detached work** (§3.5). Research runs do
 *   not lock the thread, so the user keeps asking questions; a turn submitted
 *   while another is executing is *visibly queued* rather than silently dropped
 *   or raced.
 * - **Stop acts on the active generation attempt only** (§3.5). It does not
 *   roll back committed tool effects and does not suspend a detached run, and
 *   the control says so by appearing only for the exactly-running turn.
 * - **access refusals are a state** (Lane B contract §6), never an empty
 *   transcript: a session that expired or a membership that changed says so.
 */
export function ConversationPane({
  chat,
  controller,
  projectId,
  workspace,
}: {
  chat: ProjectChatController;
  controller: ReturnType<
    typeof import("../hooks/use-project-workspace-controller").useProjectWorkspaceController
  >;
  projectId: string;
  workspace: ProjectWorkspace;
}) {
  // The dev-lens turn inspector. Its own controller, not part of `chat`: it
  // reads nothing the conversation needs and the conversation needs nothing from
  // it, so a debugging affordance never joins the state machine that drives real
  // turns. `available` is false in every deployment that did not register the
  // routes, which is every production deployment.
  const turnInspector = useTurnInspector({ projectId, threadId: chat.activeThreadId });
  const { transcriptScrollRef } = useTranscriptAutoScroll({
    revision: chat.transcript.reduce(
      (total, message) => total + message.parts.length + (message.body ? 1 : 0),
      chat.transcript.length,
    ),
  });

  const partActions = useMemo(
    () => ({
      busy: chat.submitting,
      gateFor: chat.gateFor,
      onGateDecision: (
        card: Parameters<ProjectChatController["answerGate"]>[0],
        decision: Parameters<ProjectChatController["answerGate"]>[1],
        revisionRequest?: Parameters<ProjectChatController["answerGate"]>[2],
      ) => {
        void chat.answerGate(card, decision, revisionRequest);
      },
      onGateRecovery: (card: Parameters<ProjectChatController["recoverGate"]>[0]) => {
        void chat.recoverGate(card);
      },
    }),
    [chat],
  );

  return (
    <section className={styles.conversationPane}>
      <header className={styles.conversationHeader}>
        <label>
          <select
            aria-label="Conversation thread"
            onChange={(event) => chat.selectThread(event.target.value)}
            value={chat.activeThreadId ?? ""}
          >
            {chat.threads.map((thread) => (
              <option key={thread.id} value={thread.id}>
                {chat.threadLabelFor(thread)}
                {thread.status === "idle" ? "" : ` · ${thread.status}`}
              </option>
            ))}
          </select>
          <ProjectIcon name="chevron-down" size={12} />
        </label>
        <div>
          <button
            aria-label="New thread"
            onClick={() => void chat.createThread()}
            type="button"
          >
            <ProjectIcon name="plus" size={14} />
          </button>
          <button
            aria-label="Expand conversation"
            aria-pressed={controller.focusPane === "conversation"}
            onClick={controller.toggleConversationFocus}
            type="button"
          >
            <ProjectIcon name="expand" size={14} />
          </button>
        </div>
      </header>

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
      <div className={styles.transcriptScroll} ref={transcriptScrollRef}>
        <ChatTranscript
          actions={partActions}
          contextEntities={workspace.entities}
          messages={chat.transcript}
          onInspectTurn={turnInspector.available ? turnInspector.open : undefined}
        />
      </div>
      <ChatTurnInspector inspector={turnInspector} />

      <div className={styles.workspaceComposer}>
        {chat.threadBusy ? (
          <div className={styles.planApprovalActions}>
            <span role="status">
              {chat.runningTurn
                ? "Working — new messages will queue behind this turn."
                : "Queued — waiting for the current turn to start."}
            </span>
            {chat.runningTurn ? (
              <button onClick={() => void chat.stopActiveTurn()} type="button">
                Stop
              </button>
            ) : null}
          </div>
        ) : null}
        <ProjectComposer
          // Never disabled while work is detached: the user keeps the wheel.
          disabled={chat.access !== null || chat.route !== null}
          entities={workspace.entities}
          modelPickerOpen={controller.modelPickerOpen}
          models={workspace.models}
          onEntityRemove={
            workspace.composerCapabilities.contextRefs
              ? controller.removeEntity
              : undefined
          }
          onEntitySelect={
            workspace.composerCapabilities.contextRefs
              ? controller.selectEntity
              : undefined
          }
          onModelPickerToggle={controller.toggleModelPicker}
          onModelSelect={controller.selectModel}
          onPromptChange={controller.setPrompt}
          onSubmit={(prompt, entityIds) => {
            const contextRefs = (entityIds ?? controller.selectedEntityIds)
              .map((id) => workspace.entities.find((entity) => entity.id === id))
              .filter((entity) => entity !== undefined)
              .map((entity) => ({
                objectId: entity.id,
                objectType: entity.type,
                version: null,
              }));
            void chat.submitMessage(prompt ?? controller.prompt, {
              contextRefs,
              agentProfileId:
                workspace.composerCapabilities.agentProfileSelection
                  ? (controller.selectedModel?.id ?? null)
                  : null,
            });
            controller.setPrompt("");
            controller.resetSubmissionContext();
          }}
          prompt={controller.prompt}
          selectedEntities={controller.selectedEntities}
          selectedEntityIds={controller.selectedEntityIds}
          selectedModel={controller.selectedModel}
        />
      </div>
    </section>
  );
}
