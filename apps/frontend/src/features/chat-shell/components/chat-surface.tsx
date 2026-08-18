"use client";

import { ConversationContent } from "@/features/projects/components/conversation-content";
import { ProjectComposer } from "@/features/projects/components/project-composer";
import type { ProjectChatController } from "@/features/projects/hooks/use-project-chat-controller";
import type { useProjectWorkspaceController } from "@/features/projects/hooks/use-project-workspace-controller";
import type {
  ProjectArtifact,
  ProjectWorkspace,
} from "@/features/projects/model/project-workspace";
import { useWebEditingSession } from "@/features/design-editor/hooks/use-web-editing-session";
import { useEditorShellController } from "../hooks/use-editor-shell-controller";
import {
  chatDockContent,
  chatDockDismissedBySubmission,
  chatDockOpen,
} from "../model/chat-dock";
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
  artifacts,
  chat,
  controller,
  documentIds,
  paneState,
  projectId,
  workspace,
}: {
  /** Chat-flow slice 1: the chats page's server-fetched gallery feed — the
   * rail's real cards (the artifact route's exact `loadGalleryFeed` shape).
   * Absent → the gallery keeps its honest empty state; the feed rides these
   * props, never the workspace schema (`workspace.artifacts` stays the
   * schema-hard empty tuple). */
  artifacts?: ProjectArtifact[];
  chat: ProjectChatController;
  controller: ReturnType<typeof useProjectWorkspaceController>;
  /** Artifact id → design-document id over the whole feed. Consumed by the
   * shared editing session (slice 3): the active tab's entry mounts the real
   * web render in the rail's canvas; a tab without one keeps the empty
   * canvas. */
  documentIds?: Record<string, string>;
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
  // Chat-flow slice 3: the SAME editing session the artifact route mounts
  // (documents/selection/writes/rich-text/theme), keyed only on this mount's
  // own active tab and the page's id map — the hook never sees a shell
  // controller, so the two routes stay independent mounts of one machine.
  const session = useWebEditingSession({
    activeArtifactId: shell.activeArtifactId,
    documentIds,
  });

  const activeThread =
    chat.threads.find((thread) => thread.id === chat.activeThreadId) ?? null;
  const chatTitle = activeThread ? chat.threadLabelFor(activeThread) : "Untitled";

  // The R6 dock decisions live in ../model/chat-dock as pure functions (the
  // repo's test runner has no DOM harness, so the rule is tested there and
  // consumed — never restated — here). One guard beyond the source view:
  // editorVisible additionally requires an actual artifact kind, so a
  // ?surface=web&edit=1 URL with no artifact yet collapses to the conversation
  // instead of an empty chat body. The source never hit this because it
  // fabricated default tabs — which we deliberately do not.
  const dockState = {
    artifactKind: shell.artifactKind,
    editing: shell.editing,
    panelOpen: shell.panelOpen,
    surface: shell.surface,
  };
  const editorVisible = chatDockOpen(dockState);
  const dockContent = chatDockContent(dockState);

  // W4.8a law, per mount: rich-text is enabled under the SAME condition that
  // mounts THIS route's editing dock (the .chatBody web-inspector branch) over
  // a real web document. Outside it the canvas cancels any session the bridge
  // starts, so a double-click on the read-only render changes nothing.
  const webEditingActive =
    dockContent === "web-inspector" && session.activeDocumentId !== null;

  // The artifact route's own fallback (editor-surface.tsx): a live canvas
  // selection names the schema to render; with nothing selected the inspector
  // falls back to this mount's shell state (the ?selection= pane param).
  const inspectorSelection =
    session.webSelection.selection?.schema.selection ?? shell.inspectorSelection;

  return (
    <main
      className={`${styles.shell} ${shell.panelOpen ? styles.shellPanelOpen : ""} ${shell.artifactMaximized ? styles.shellArtifactMaximized : ""}`}
      data-artifact-id={shell.activeArtifactId ?? undefined}
      data-artifact-kind={shell.artifactKind ?? "none"}
      data-editing={editorVisible}
      data-project-id={projectId}
      data-selected-node={session.webSelection.selection?.node.id}
      data-selected-schema={
        session.webSelection.selection
          ? `${session.webSelection.selection.schema.selection}${session.webSelection.selection.schema.layoutOnly ? ":layout-only" : ""}`
          : undefined
      }
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
          {dockContent === "web-inspector" ? (
            <div className={styles.inspectorDock}>
              <WebInspector
                // Keyed on the SELECTED NODE only — never the document version.
                // A per-write version key remounted the whole inspector on
                // every edit (the founder-observed defect); the controller's
                // own state already reflects the user's edit, so re-hydration
                // belongs to selection changes alone.
                key={session.webSelection.selection?.node.id ?? "canvas"}
                customComponentForm={session.customComponentForm}
                error={session.inspectorError}
                note={session.writes.note}
                addressing={session.addressing}
                hydrated={session.webSelection.selection?.hydrated}
                layers={session.layerRows}
                onReplaceImage={session.onReplaceImage}
                onSelectLayer={session.onSelectLayer}
                onSelectionChange={shell.selectInspectorElement}
                richTextRange={session.richTextRange}
                selection={inspectorSelection}
                themeColors={session.themeColors}
              />
            </div>
          ) : null}
          {dockContent === "ad-inspector" ? (
            <div className={styles.inspectorDock}>
              <ImageInspector
                onSelectionChange={shell.selectInspectorElement}
                selection={shell.inspectorSelection}
              />
            </div>
          ) : null}
          {dockContent === "conversation" ? (
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
                // R6 dismiss-on-send: a message the agent ACCEPTED closes the
                // editing dock and restores the conversation the user is now
                // talking in. A refused (`failed`) or empty/threadless
                // (`not_submitted`) submit leaves them mid-edit. The rule is
                // evaluated over the whole status union — before the early
                // return — so the pure decision in ../model/chat-dock is the
                // one that actually runs.
                if (chatDockDismissedBySubmission(accepted.status)) {
                  shell.setEditing(false);
                }
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
        activeDocumentId={session.activeDocumentId}
        artifacts={artifacts ?? []}
        artifactKind={shell.artifactKind}
        artifactMaximized={shell.artifactMaximized}
        artifactTitle={shell.artifactTitle}
        canvasControlsRef={session.canvasControls}
        canvasReloadToken={session.reloadNonce}
        editing={shell.editing}
        onActivateArtifact={shell.activateArtifact}
        onCanvasSelect={session.webSelection.onSelect}
        onCloseArtifact={shell.closeArtifact}
        onOpenGallery={shell.openGallery}
        onRichTextCommit={session.onRichTextCommit}
        onRichTextSessionChange={session.onRichTextSessionChange}
        richTextBusy={session.writes.busy}
        richTextEnabled={webEditingActive}
        richTextTheme={session.theme}
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
        redoDisabled={session.redoDisabled}
        selectedCanvasNodeId={session.webSelection.selection?.node.id ?? null}
        surface={shell.surface}
        undoDisabled={session.undoDisabled}
      />
    </main>
  );
}
