"use client";

import { ConversationContent } from "@/features/projects/components/conversation-content";
import { ProjectComposer } from "@/features/projects/components/project-composer";
import type { ProjectChatController } from "@/features/projects/hooks/use-project-chat-controller";
import type { useProjectWorkspaceController } from "@/features/projects/hooks/use-project-workspace-controller";
import type { ProjectWorkspace } from "@/features/projects/model/project-workspace";
import { useEditorShellController } from "../hooks/use-editor-shell-controller";
import { chatSurfaceUrlState } from "../model/chat-surface-params";
import { ArtifactStage } from "./artifact-stage";
import { ChatShellHeader } from "./chat-shell-header";
import { ImageInspector } from "./image-inspector";
import styles from "./chat-shell.module.css";
import { WebInspector } from "./web-inspector";

// The chats route's view layer (Phase C, C-3): the co-founder's chat-shell
// geometry — chat pane (header + conversation stage + composer dock) beside
// the artifact rail — re-authored from the branch's chat-shell-view around
// OUR production chat plane. The design's conversation area was an empty
// <div> and its composer was wired to no-ops, so adoption is pure frame
// adoption: our transcript, gate cards, queue/Stop banner, refusal alerts,
// and composer slot into the design's slots; all chat wiring is untouched.
//
// Founder rulings in force (2026-08-17):
// - R7: no embedded <ApplicationShell> — the (protected) layout owns the app
//   shell; this component's root is main.shell.
// - R4: no in-pane thread switcher or new-thread affordance — the sidebar
//   owns thread switching.
// - R6 (accepted for v1): while editing a web/ad artifact the inspector
//   replaces the conversation column — a running turn's gate or Stop is
//   invisible mid-edit. The founder personally owns revisiting this during
//   editor integration.
// - R5: the session menu's Delete renders but is inert (see the menu
//   controller).
//
// URL pane state (?surface=/edit=/selection=, ruling R2) is read once at
// mount as initial state; pane toggles deliberately do not write back to the
// URL in this phase (known deferral — the dummy behaves the same way). The
// W-lane's split view hydrates this same mount with a real canvas later.

export function ChatSurface({
  chat,
  controller,
  paneState,
  projectId,
  workspace,
}: {
  chat: ProjectChatController;
  controller: ReturnType<typeof useProjectWorkspaceController>;
  paneState: { edit?: string; selection?: string; surface?: string };
  projectId: string;
  workspace: ProjectWorkspace;
}) {
  const urlState = chatSurfaceUrlState(paneState);
  const shell = useEditorShellController({
    editing: urlState.editing,
    inspectorSelection: urlState.inspectorSelection,
    panelOpen: urlState.panelOpen,
    projectId,
    surface: urlState.surface,
  });

  const activeThread =
    chat.threads.find((thread) => thread.id === chat.activeThreadId) ?? null;
  const chatTitle = activeThread ? chat.threadLabelFor(activeThread) : "Untitled";

  // One guard beyond the source view: editorVisible additionally requires an
  // actual artifact kind, so a ?surface=web&edit=1 URL with no artifact yet
  // (workspace.artifacts is empty until W1.3) collapses to the conversation
  // instead of an empty chat body. The source never hit this because it
  // fabricated default tabs — which we deliberately do not.
  const editorVisible =
    shell.panelOpen &&
    shell.surface === "artifact" &&
    shell.editing &&
    shell.artifactKind !== null;

  return (
    <main
      className={`${styles.shell} ${shell.panelOpen ? styles.shellPanelOpen : ""} ${shell.artifactMaximized ? styles.shellArtifactMaximized : ""}`}
      data-artifact-id={shell.activeArtifactId ?? undefined}
      data-artifact-kind={shell.artifactKind ?? "none"}
      data-editing={editorVisible}
      data-project-id={projectId}
    >
      <section className={styles.chatPane}>
        <ChatShellHeader
          chatId={chat.activeThreadId ?? undefined}
          onArchive={() => {
            if (chat.activeThreadId) void chat.archiveThread(chat.activeThreadId);
          }}
          onRename={(title) => {
            if (chat.activeThreadId) void chat.renameThread(chat.activeThreadId, title);
          }}
          onToggleArtifactPanel={shell.toggleArtifactPanel}
          panelOpen={shell.panelOpen}
          projectId={projectId}
          title={chatTitle}
        />
        <div className={styles.chatBody}>
          {editorVisible && shell.artifactKind === "web" ? (
            <div className={styles.inspectorDock}>
              <WebInspector
                onSelectionChange={shell.selectInspectorElement}
                selection={shell.inspectorSelection}
              />
            </div>
          ) : null}
          {editorVisible && shell.artifactKind === "ad" ? (
            <div className={styles.inspectorDock}>
              <ImageInspector
                onSelectionChange={shell.selectInspectorElement}
                selection={shell.inspectorSelection}
              />
            </div>
          ) : null}
          {!editorVisible ? (
            <div
              aria-label="Conversation"
              className={`${styles.conversationStage} flex min-h-0 flex-col`}
            >
              <ConversationContent
                chat={chat}
                contextHandoffError={controller.contextHandoffError}
                projectId={projectId}
                workspace={workspace}
              />
            </div>
          ) : null}
        </div>
        <div className={styles.composerDock}>
          <div className={styles.composerFrame}>
            <ProjectComposer
              // Never disabled while work is detached: the user keeps the wheel.
              disabled={chat.access !== null || chat.route !== null}
              entities={controller.composerEntities}
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
              onSubmit={async (prompt, entityIds) => {
                const contextRefs = (entityIds ?? controller.selectedEntityIds)
                  .map((id) =>
                    controller.composerEntities.find((entity) => entity.id === id),
                  )
                  .filter((entity) => entity !== undefined)
                  .map((entity) => ({
                    objectId: entity.id,
                    objectType: entity.type,
                    version: entity.version ?? null,
                  }));
                const accepted = await chat.submitMessage(prompt, {
                  contextRefs,
                  agentProfileId:
                    workspace.composerCapabilities.agentProfileSelection
                      ? (controller.selectedModel?.id ?? null)
                      : null,
                });
                if (accepted.status !== "accepted") return false;
                controller.completeSubmissionContext(
                  contextRefs.map((reference) => reference.objectId),
                );
                return true;
              }}
              prompt={controller.prompt}
              selectedEntities={controller.selectedEntities}
              selectedEntityIds={controller.selectedEntityIds}
              selectedModel={controller.selectedModel}
            />
          </div>
        </div>
      </section>
      <ArtifactStage
        activeArtifactId={shell.activeArtifactId}
        artifacts={workspace.artifacts}
        artifactKind={shell.artifactKind}
        artifactMaximized={shell.artifactMaximized}
        artifactTitle={shell.artifactTitle}
        editing={shell.editing}
        onActivateArtifact={shell.activateArtifact}
        onCloseArtifact={shell.closeArtifact}
        onOpenGallery={shell.openGallery}
        onOpenGalleryArtifact={(artifact) =>
          shell.openArtifact({
            id: artifact.id,
            kind: artifact.source.type === "website" ? "web" : "ad",
            title: artifact.title,
          })
        }
        onRenameArtifact={(title) => {
          if (shell.activeArtifactId) {
            shell.setArtifactTitleFor(shell.activeArtifactId, title);
          }
        }}
        onRenameArtifactFor={shell.setArtifactTitleFor}
        onToggleMaximized={shell.toggleArtifactMaximized}
        onTogglePanel={shell.toggleArtifactPanel}
        onToggleEditing={() => shell.setEditing(!shell.editing)}
        openArtifacts={shell.openArtifacts}
        projectTitle={workspace.title}
        surface={shell.surface}
      />
    </main>
  );
}
