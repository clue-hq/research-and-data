"use client";

import { useEffect, useRef } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ConversationContent } from "@/features/projects/components/conversation-content";
import { ProjectComposer } from "@/features/projects/components/project-composer";
import type { ProjectChatController } from "@/features/projects/hooks/use-project-chat-controller";
import { useDesignReferenceAttachments } from "@/features/projects/hooks/use-design-reference-attachments";
import {
  DESIGN_REFERENCE_ACCEPT,
  MAX_DESIGN_REFERENCE_ATTACHMENTS,
} from "@/features/projects/model/design-reference-attachments";
import type { useProjectWorkspaceController } from "@/features/projects/hooks/use-project-workspace-controller";
import type {
  ProjectArtifact,
  ProjectWorkspace,
} from "@/features/projects/model/project-workspace";
import { useSceneEditingSession } from "@/features/design-editor/hooks/use-scene-editing-session";
import { useWebEditingSession } from "@/features/design-editor/hooks/use-web-editing-session";
import { useEditorShellController } from "../hooks/use-editor-shell-controller";
import { artifactToAutoOpen } from "../model/artifact-auto-open";
import {
  chatDockContent,
  chatDockDismissedBySubmission,
  chatDockOpen,
} from "../model/chat-dock";
import {
  chatSurfacePaneParams,
  chatSurfaceUrlState,
} from "../model/chat-surface-params";
import {
  editTargetChips,
  editTargetContextRefs,
} from "../model/edit-targets";
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
// mount as initial state, and — since chat-flow slice 5 — written back on
// every pane change, so every editing state the user reaches is a shareable
// deep link. Hydration stays one-directional: the effect below only calls
// router.replace; it never feeds the URL back into the shell state.

/** One stable empty feed, so a page mounted without artifacts does not hand
 * the auto-open effect a new array identity on every render. */
const NO_ARTIFACTS: ProjectArtifact[] = [];

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
  // AD2.7: one session per LANE, each gated on this mount's own active tab
  // kind. React forbids a conditional hook, so both are always called and the
  // kind rides in as `enabled` — the disabled one touches no transport
  // (audit finding F3: an ad tab used to run the web theme/document fetches
  // and swallow their 409s).
  const session = useWebEditingSession({
    activeArtifactId: shell.activeArtifactId,
    documentIds,
    enabled: shell.artifactKind === "web",
  });
  const sceneSession = useSceneEditingSession({
    activeArtifactId: shell.activeArtifactId,
    documentIds,
    enabled: shell.artifactKind === "ad",
  });
  // Exactly one lane can be enabled, so this is the active document either
  // way — the stage's canvas branch picks the surface by kind.
  const activeDocumentId =
    session.activeDocumentId ?? sceneSession.activeDocumentId;
  const designReferencesEnabled =
    chat.designLegOpen &&
    shell.artifactKind === "ad" &&
    sceneSession.activeDocumentId !== null;
  const referenceAttachments = useDesignReferenceAttachments({
    enabled: designReferencesEnabled,
  });
  // Same gate as the reference images above: a `design_node` ref only means
  // anything beside the open design leg's document, and the backend refuses a
  // submission carrying one otherwise — a canvas selection made outside an
  // open leg (a gallery-opened ad, a closed leg) must stay a canvas fact, not
  // become a context ref that walls off every message in the thread.
  const editTargetsEnabled =
    chat.designLegOpen &&
    shell.artifactKind === "ad" &&
    sceneSession.activeDocumentId !== null;
  const targetChips = editTargetsEnabled
    ? editTargetChips(sceneSession.scene, sceneSession.selectedIds)
    : [];

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
  // falls back to this mount's shell state (the ?selection= pane param). The
  // two lanes are mutually exclusive (one `enabled` each), so at most one of
  // the first two terms is ever non-null.
  const inspectorSelection =
    session.webSelection.selection?.schema.selection ??
    sceneSession.selection?.selection ??
    shell.inspectorSelection;

  // Chat-flow slice 5: the pane state writes back to the URL, so every state
  // the user reaches (rail open, surface, Edit, inspector schema) is a
  // shareable deep link — the closing half of the R2 vocabulary. The
  // serializer is pure (../model/chat-surface-params); this effect only
  // transports its output.
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const {
    edit: editParam,
    selection: selectionParam,
    surface: surfaceParam,
  } = chatSurfacePaneParams({
    artifactKind: shell.artifactKind,
    editing: shell.editing,
    // The SAME schema the inspector is rendering — a live canvas selection
    // names its schema, else the shell's own. That is exactly what ?selection=
    // hydrates; the canvas NODE id is deliberately never serialized (it is
    // document-local and would not survive a share, and the shared vocabulary
    // has no artifact identity at all — a deep link restores the pane state,
    // not the open tab).
    inspectorSelection,
    panelOpen: shell.panelOpen,
    rawSurface: paneState.surface,
    surface: shell.surface,
  });
  // Genweb slice 3 (B5), founder requirements 1 + 6: the gallery feed and any
  // open canvas refresh exactly when a durable design-leg frame for THIS thread
  // says the document moved. Never a timer, never a poll — the two counters are
  // bumped by the chat controller from the stream, and the rule that decides
  // which frame bumps which is the pure `designRefreshForEvent`.
  //
  // The feed is server-fetched by the chats page (`loadGalleryFeed`, a
  // server-only repository), so `router.refresh()` IS the client's re-fetch of
  // it: the page re-runs and hands down fresh `artifacts`/`documentIds` props
  // with no client state lost — which is also what lets the auto-open below
  // notice the born document by comparing props, rather than remounting.
  const { canvasRevision, feedRevision } = chat.designRefresh;
  useEffect(() => {
    if (feedRevision === 0) return;
    router.refresh();
  }, [feedRevision, router]);
  const reloadWebCanvas = session.onWriteReload;
  const reloadSceneCanvas = sceneSession.onWriteReload;
  useEffect(() => {
    if (canvasRevision === 0) return;
    // The SAME seam a committed inspector write uses — one reload mechanism,
    // whether the version was advanced by hand or by the design agent. Both
    // lanes are bumped: the stage takes the SUM as its reload token, and the
    // frame that fired names a document, not a kind.
    reloadWebCanvas();
    reloadSceneCanvas();
  }, [canvasRevision, reloadSceneCanvas, reloadWebCanvas]);

  // Founder ruling F2 **(b)**, 2026-08-19 — superseding option (a) for v1: the
  // leg-born document opens ITSELF next to the Gallery, so the user watches the
  // page land instead of hunting for the card. The whole rule is the pure
  // `../model/artifact-auto-open`; this effect is only its transport, and it
  // reuses the exact `shell.openArtifact` the gallery card's own click uses (so
  // the tab, its activation, and the R6 dock choreography behave identically
  // whether the user opened it or the leg did).
  //
  // The trigger is the FEED, never the frame: `leg.opened` carries only a leg
  // id and names no document, and on a cold load the replayed backlog re-fires
  // it — keying off the frame would re-open the tab on every page load. What
  // the frame does do is refresh the feed, so the born card arrives in props on
  // its own; everything already there at mount is banked as known and can never
  // auto-open.
  const knownArtifactIds = useRef<Set<string> | null>(null);
  const openArtifact = shell.openArtifact;
  const feedArtifacts = artifacts ?? NO_ARTIFACTS;
  useEffect(() => {
    const known = knownArtifactIds.current;
    if (known === null) {
      // The mount snapshot. Taken on the first commit rather than during
      // render (no render-phase side effects), which is the same set: the
      // chats page awaits `loadGalleryFeed` server-side, so the first client
      // render already holds the complete feed.
      knownArtifactIds.current = new Set(
        feedArtifacts.map((artifact) => artifact.id),
      );
      return;
    }
    const opening = artifactToAutoOpen({
      activeThreadId: chat.activeThreadId,
      artifacts: feedArtifacts,
      knownArtifactIds: known,
    });
    // Bank everything this delivery carried — including the one being opened —
    // before acting on the decision. That is what makes a document open at
    // most once: a tab the user then closes stays closed, and the next feed
    // refresh (the URL write-back below re-renders the page too) is inert.
    for (const artifact of feedArtifacts) known.add(artifact.id);
    if (opening === null) return;
    openArtifact(opening);
  }, [chat.activeThreadId, feedArtifacts, openArtifact]);

  useEffect(() => {
    // Compose over the LIVE query so params we do not own (?handoff=, anything
    // future) survive; only the three pane keys are ours to rewrite.
    const query = new URLSearchParams(searchParams.toString());
    query.delete("surface");
    query.delete("edit");
    query.delete("selection");
    if (surfaceParam) query.set("surface", surfaceParam);
    if (editParam) query.set("edit", editParam);
    if (selectionParam) query.set("selection", selectionParam);
    const next = query.toString();
    // Loop guard: replace only on a real difference. This is also what makes
    // the write-back converge WITH the workspace controller's handoff cleanup
    // (same pathname, preserved params) instead of fighting it.
    if (next === searchParams.toString()) return;
    // replace, never push: pane toggles must not grow browser history.
    router.replace(`${pathname}${next ? `?${next}` : ""}`, { scroll: false });
  }, [editParam, pathname, router, searchParams, selectionParam, surfaceParam]);

  return (
    <main
      className={`${styles.shell} ${shell.panelOpen ? styles.shellPanelOpen : ""} ${shell.artifactMaximized ? styles.shellArtifactMaximized : ""}`}
      data-artifact-id={shell.activeArtifactId ?? undefined}
      data-artifact-kind={shell.artifactKind ?? "none"}
      data-editing={editorVisible}
      data-project-id={projectId}
      data-selected-node={
        session.webSelection.selection?.node.id ??
        sceneSession.primaryNodeId ??
        undefined
      }
      data-selected-schema={
        session.webSelection.selection
          ? `${session.webSelection.selection.schema.selection}${session.webSelection.selection.schema.layoutOnly ? ":layout-only" : ""}`
          : dockContent === "ad-inspector" && sceneSession.selection
            ? `${sceneSession.selection.selection}${sceneSession.selection.suppressAutoLayoutSection ? ":no-auto-layout" : ""}`
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
                // The canvas key carries the theme's page surface, so the one time the
                // theme lands after mount the canvas inspector re-seeds from it
                // (the web lane hydrates at mount, not live).
                key={session.webSelection.selection?.node.id ?? `canvas:${session.canvasHydrated?.backgroundColor ?? ""}`}
                customComponentForm={session.customComponentForm}
                error={session.inspectorError}
                note={session.writes.note}
                addressing={session.addressing}
                hydrated={session.webSelection.selection?.hydrated ?? session.canvasHydrated}
                layers={session.layerRows}
                // W5.1 (§5): the mapper's fallback flag — embeds (item 32) and
                // the interactive components (item 33) land on the container
                // view and get Layout(-padding) only.
                layoutOnly={session.webSelection.selection?.schema.layoutOnly}
                onReplaceImage={session.onReplaceImage}
                onSelectLayer={session.onSelectLayer}
                onSelectionChange={shell.selectInspectorElement}
                // F5 task 19 (FLAGGED): the page/route controls, present only while
                // no node is selected (the session decides).
                pageSection={session.pageSection}
                richTextRange={session.richTextRange}
                selection={inspectorSelection}
                themeColors={session.themeColors}
              />
            </div>
          ) : null}
          {dockContent === "ad-inspector" ? (
            <div className={styles.inspectorDock}>
              <ImageInspector
                // Keyed on the SELECTED NODE only, exactly as the web branch
                // above. Values need no remount to resynchronize — every bound
                // field derives from live hydrated state (AD4.R); remounting
                // resets UI facts (open sections, drafts), which is right
                // exactly when the selection changes.
                key={sceneSession.primaryNodeId ?? "canvas"}
                addressing={sceneSession.addressing}
                arrange={sceneSession.arrange}
                error={sceneSession.inspectorError}
                fontOptions={sceneSession.fontOptions}
                hydrated={sceneSession.hydrated}
                imageAi={sceneSession.imageAi}
                // AD4.R-10 / GATE G-H (founder-ruled 2026-08-22): while an
                // agent turn is in flight on THIS thread, the human may not
                // operate the inspector — "we cannot let humans change any
                // value when the agents are at work with designing".
                //
                // `chat.threadBusy` is the controller's own already-public fact
                // (`selectTurnQueueState`: a running turn, or one queued behind
                // it), the same one the conversation view reads for its busy
                // affordance. Nothing new is derived and nothing is written
                // back: this is a READ of the chat controller, so no chat-side
                // behaviour — composer, sending, gates, queueing, mid-turn
                // steering — can move because of this line, in either
                // direction (the founder's chat-status-quo addendum).
                //
                // The gate is a TURN in flight, not an open design leg: a leg
                // stays open across turns, and interleaved manual edits BETWEEN
                // turns are the ratified genweb feature this must not touch.
                inspectorDisabled={chat.threadBusy}
                layers={sceneSession.layerRows}
                note={sceneSession.note}
                onReplaceImage={sceneSession.onReplaceImage}
                onSelectLayer={sceneSession.onSelectLayer}
                onSelectionChange={shell.selectInspectorElement}
                onToggleLayer={sceneSession.onToggleLayer}
                pageless={sceneSession.pageless}
                palette={sceneSession.palette}
                selectedIds={sceneSession.selectedIds}
                selection={inspectorSelection}
                suppressAutoLayoutSection={
                  sceneSession.selection?.suppressAutoLayoutSection
                }
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
        <div
          className={`${styles.composerDock} ${
            targetChips.length ? styles.composerDockWithTargets : ""
          }`}
        >
          <div className={styles.composerFrame}>
            {targetChips.length ? (
              <div aria-label="Edit targets" className={styles.editTargetBar}>
                <span className={styles.editTargetLabel}>Editing</span>
                <div className={styles.editTargetList}>
                  {targetChips.map((target) => (
                    <span className={styles.editTargetChip} key={target.nodeId}>
                      <span className={styles.editTargetName}>{target.label}</span>
                      <button
                        aria-label={`Remove ${target.label} edit target`}
                        className={styles.editTargetRemove}
                        onClick={() =>
                          sceneSession.onSelectLayer(target.nodeId, true)
                        }
                        type="button"
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              </div>
            ) : null}
            <ProjectComposer
              attachmentAccept={DESIGN_REFERENCE_ACCEPT}
              attachmentError={
                designReferencesEnabled ? referenceAttachments.error : null
              }
              attachmentInputDisabled={
                referenceAttachments.attachments.length >=
                MAX_DESIGN_REFERENCE_ATTACHMENTS
              }
              attachmentLabel="Attach reference images"
              attachments={
                designReferencesEnabled
                  ? [...referenceAttachments.attachments]
                  : []
              }
              // Never disabled while work is detached: the user keeps the wheel.
              disabled={chat.access !== null || chat.route !== null}
              entities={controller.composerEntities}
              modelPickerOpen={controller.modelPickerOpen}
              models={workspace.models}
              onAttachmentFiles={
                designReferencesEnabled ? referenceAttachments.onFiles : undefined
              }
              onAttachmentRemove={
                designReferencesEnabled ? referenceAttachments.remove : undefined
              }
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
                // Snapshot references synchronously before any await. A queued turn owns these
                // exact asset ids even if uploads or selection change before the POST returns.
                const referenceSnapshot = designReferencesEnabled
                  ? referenceAttachments.snapshotContextRefs()
                  : [];
                if (
                  referenceAttachments.attachments.length > 0 &&
                  referenceSnapshot === null
                ) {
                  return false;
                }
                // Snapshot ids before the first await inside the scene session.
                // A queued turn keeps this set even if the user changes the
                // canvas selection while optimistic writes finish or the POST runs.
                const editTargetSnapshot = editTargetsEnabled
                  ? await sceneSession.snapshotEditTargets()
                  : null;
                if (targetChips.length > 0 && editTargetSnapshot === null) {
                  return false;
                }
                const entityContextRefs = (entityIds ?? controller.selectedEntityIds)
                  .map((id) =>
                    controller.composerEntities.find((entity) => entity.id === id),
                  )
                  .filter((entity) => entity !== undefined)
                  .map((entity) => ({
                    objectId: entity.id,
                    objectType: entity.type,
                    version: entity.version ?? null,
                  }));
                const contextRefs = [
                  ...entityContextRefs,
                  ...editTargetContextRefs(editTargetSnapshot),
                  ...(referenceSnapshot ?? []),
                ];
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
                referenceAttachments.clear();
                controller.completeSubmissionContext(
                  entityContextRefs.map((reference) => reference.objectId),
                );
                return true;
              }}
              prompt={controller.prompt}
              sendDisabled={
                designReferencesEnabled && referenceAttachments.submissionBlocked
              }
              selectedEntities={controller.selectedEntities}
              selectedEntityIds={controller.selectedEntityIds}
              selectedModel={controller.selectedModel}
            />
          </div>
        </div>
      </section>
      <ArtifactStage
        activeArtifactId={shell.activeArtifactId}
        activeDocumentId={activeDocumentId}
        // F5 task 18: the header's page switcher and the canvas read ONE
        // value — the web editing session's active page.
        activePageId={session.activePageId}
        onPageChange={session.setActivePageId}
        pages={session.pages}
        artifacts={feedArtifacts}
        artifactKind={shell.artifactKind}
        artifactMaximized={shell.artifactMaximized}
        artifactTitle={shell.artifactTitle}
        canvasControlsRef={session.canvasControls}
        canvasReloadToken={session.reloadNonce + sceneSession.reloadNonce}
        exportPreview={sceneSession.exportPreview}
        exportStatus={sceneSession.exportStatus}
        onRequestExportPreview={sceneSession.requestExportPreview}
        onSceneChange={sceneSession.onSceneChange}
        onSceneFitZoom={sceneSession.onFitZoom}
        onSceneGestureZoom={sceneSession.onGestureZoom}
        onSceneHistoryChange={sceneSession.onHistoryChange}
        // AD4.C / Ruling C-3: a committed canvas gesture rides the SAME write
        // path the inspector's rows do — the session's `applyOps` (optimistic
        // engine apply → repaint → edit-queue persist), so a drag is one
        // atomic batch, one undo frame, and ⌘Z needs nothing new.
        onSceneAppliedOperations={sceneSession.writes.persistAppliedOps}
        onSceneOperations={sceneSession.writes.applyOps}
        onSceneSelect={sceneSession.onSelectCanvas}
        onSceneZoomChange={sceneSession.onZoomChange}
        sceneCanvasControlsRef={sceneSession.canvasControls}
        // AD4.C / Ruling C-4 — GATE G-H, the canvas half of the same ruling
        // `inspectorDisabled` above implements, off the same already-public
        // fact: while a turn is in flight on THIS thread the human may not
        // change values, so drag and resize are off and the handles go with
        // them. Selection stays live — looking is not changing.
        sceneGestureDisabled={chat.threadBusy}
        sceneSelectedNodeId={sceneSession.primaryNodeId}
        sceneZoomLabel={sceneSession.zoom}
        sceneZoomOverride={sceneSession.zoomOverride}
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
        // AD3.3: the header carries ONE pair of history-row disables, and the
        // artifact on screen decides which lane's stacks they describe — the
        // same kind switch that gates the two sessions above. Without it an ad
        // would read the (always-empty) web session's depths and its rows could
        // never be offered.
        redoDisabled={
          shell.artifactKind === "ad"
            ? sceneSession.redoDisabled
            : session.redoDisabled
        }
        selectedCanvasNodeId={session.webSelection.selection?.node.id ?? null}
        surface={shell.surface}
        undoDisabled={
          shell.artifactKind === "ad"
            ? sceneSession.undoDisabled
            : session.undoDisabled
        }
      />
    </main>
  );
}
