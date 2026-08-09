"use client";

import { useMemo } from "react";
import type { ProjectWorkspace } from "../model/project-workspace";
import type { ProjectChatController } from "../hooks/use-project-chat-controller";
import { useTranscriptAutoScroll } from "../hooks/use-transcript-auto-scroll";
import { useTurnInspector } from "../hooks/use-turn-inspector";
import { CanvasInspector } from "./canvas-inspector";
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
 *   the control says so by only appearing while a turn is live.
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
      ) => {
        void chat.answerGate(card, decision);
      },
    }),
    [chat],
  );

  if (controller.inspectorOpen) {
    return (
      <section className={styles.conversationPane} data-mode="inspector">
        <header className={styles.conversationHeader}>
          <strong>
            {chat.activeThread ? chat.threadLabelFor(chat.activeThread) : "Conversation"}
          </strong>
          <div>
            <button
              aria-label="Close inspector"
              className={styles.activeTool}
              onClick={() => controller.setInspectorOpen(false)}
              type="button"
            >
              <ProjectIcon name="edit-active" size={14} />
            </button>
          </div>
        </header>
        <CanvasInspector
          ctaLabel={controller.ctaLabel}
          headlineAlign={controller.headlineAlign}
          headlineFont={controller.headlineFont}
          headlineSize={controller.headlineSize / 2}
          headlineWeight={controller.headlineWeight}
          heroImageFit={controller.heroImageFit}
          heroImageRadius={controller.heroImageRadius}
          onCtaLabelChange={controller.setCtaLabel}
          onHeadlineAlignChange={controller.setHeadlineAlign}
          onHeadlineColorChange={controller.setHeadlineColor}
          onHeadlineFontChange={controller.setHeadlineFont}
          onHeadlineSizeChange={(size) => controller.setHeadlineSize(size * 2)}
          onHeadlineWeightChange={controller.setHeadlineWeight}
          onHeroImageFitChange={controller.setHeroImageFit}
          onHeroImageRadiusChange={controller.setHeroImageRadius}
          onHeroImageReplace={controller.replaceHeroImage}
          selection={controller.inspectorSelection}
        />
        <div className={styles.inspectorComposer}>
          <span className={styles.selectionTag}>
            heading 1{" "}
            <button onClick={() => controller.setInspectorSelection("canvas")} type="button">
              ×
            </button>
          </span>
          <ProjectComposer
            entities={workspace.contextEntities}
            modelPickerOpen={controller.modelPickerOpen}
            models={workspace.models}
            onEntityRemove={workspace.composerCapabilities.contextRefs
              ? controller.removeEntity
              : undefined}
            onEntitySelect={workspace.composerCapabilities.contextRefs
              ? controller.selectEntity
              : undefined}
            onModelPickerToggle={controller.toggleModelPicker}
            onModelSelect={controller.selectModel}
            onPromptChange={controller.setPrompt}
            onSubmit={(prompt) => void chat.submitMessage(prompt ?? controller.prompt)}
            prompt={controller.prompt}
            selectedEntities={controller.selectedEntities}
            selectedEntityIds={controller.selectedEntityIds}
            selectedModel={controller.selectedModel}
          />
        </div>
      </section>
    );
  }

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
          {controller.selectedArtifact ? (
            <button
              aria-label="Open canvas inspector"
              onClick={() => controller.setInspectorOpen(true)}
              type="button"
            >
              <ProjectIcon name="edit" size={14} />
            </button>
          ) : null}
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
          messages={chat.transcript}
          onInspectTurn={turnInspector.available ? turnInspector.open : undefined}
        />
      </div>
      <ChatTurnInspector inspector={turnInspector} />

      <div className={styles.workspaceComposer}>
        {chat.busy ? (
          <div className={styles.planApprovalActions}>
            <span role="status">
              {chat.activeTurnId
                ? "Working — new messages will queue behind this turn."
                : "Queued — waiting for the current turn to start."}
            </span>
            {chat.activeTurnId ? (
              <button onClick={() => void chat.stopActiveTurn()} type="button">
                Stop
              </button>
            ) : null}
          </div>
        ) : null}
        <ProjectComposer
          // Never disabled while work is detached: the user keeps the wheel.
          disabled={chat.access !== null || chat.route !== null}
          entities={workspace.contextEntities}
          modelPickerOpen={controller.modelPickerOpen}
          models={workspace.models}
          onEntityRemove={workspace.composerCapabilities.contextRefs
            ? controller.removeEntity
            : undefined}
          onEntitySelect={workspace.composerCapabilities.contextRefs
            ? controller.selectEntity
            : undefined}
          onModelPickerToggle={controller.toggleModelPicker}
          onModelSelect={controller.selectModel}
          onPromptChange={controller.setPrompt}
          onSubmit={(prompt) => {
            void chat.submitMessage(prompt ?? controller.prompt);
            controller.setPrompt("");
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
