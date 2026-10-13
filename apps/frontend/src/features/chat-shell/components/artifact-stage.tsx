"use client";

import type {
  ChatShellArtifactKind,
  ChatShellOpenArtifact,
} from "../model/chat-shell";
import type {
  ImageExportFormat,
  ImageExportPreview,
  ImageExportScale,
} from "../model/image-export";
import {
  WebArtifactCanvas,
  type WebAnnotationsCanvasBinding,
  type WebArtifactCanvasControls,
  type WebRichTextSessionState,
} from "@/features/design-editor/components/web-artifact-canvas";
import {
  SceneArtifactCanvas,
  type SceneCanvasControls,
} from "@/features/design-editor/components/scene-artifact-canvas";
import type { ScenePalette } from "@/features/design-editor/adapter/scene-palette";
import type {
  SceneDocumentHistory,
  SceneEngineStatus,
} from "@/features/design-editor/hooks/use-scene-document";
import type {
  Operation,
  PageId,
  Scene,
} from "@/features/design-editor/engine/scene/contracts";
import type { SceneExportStatus } from "@/features/design-editor/adapter/scene-export";
import {
  initialVeilState,
  nextVeilState,
  type VeilRenderKind,
} from "@/features/design-editor/adapter/generating-veil";
import {
  GeneratingGlow,
  WebsiteGeneratingVeil,
} from "@/features/design-editor/components/generating";
import type {
  WebElementAddress,
  WebSelection,
} from "@/features/design-editor/engine/webBridge";
import type {
  RichTextDocument,
  WebFragmentTextOverride,
  WebTheme,
} from "@/features/design-editor/engine/webDocuments";
import { useState, type ReactNode, type RefObject } from "react";
import { ProjectGallery } from "@/features/gallery/components/project-gallery";
import type { useProjectDocumentTabs } from "@/features/projects/hooks/use-project-document-tabs";
import { ProjectDocumentSurface } from "@/features/projects/components/project-document-surface";
import { ProjectTargetAccounts } from "@/features/accounts/components/project-target-accounts";
import type { ChatContextRef } from "@/features/projects/model/chat-context-handoff";
import type { GalleryArtifact } from "@/features/gallery/model/project-gallery";
import type { ProjectArtifact } from "@/features/projects/model/project-workspace";
import type { EditorShellSurface } from "../hooks/use-editor-shell-controller";
import type {
  ArtifactPageOption,
  ArtifactPreviewDevice,
} from "../hooks/use-artifact-toolbar-controller";
import { AdDesigningLock, sceneAgentMotionActive } from "@/features/design-editor/components/generating";
import { isWebsiteKind } from "../model/artifact-kind";
import { ArtifactHeader } from "./artifact-header";
import { ArtifactTabs } from "./artifact-tabs";
import styles from "./chat-shell.module.css";
// The cofounder's approved motion (handoff ad4f30bb) is a plain stylesheet, not
// a CSS module — its class names are the contract between the sheet and the
// components. Imported ONCE here, where the output pane is composed; the App
// Router allows a global sheet from a client component.
import "@/features/design-editor/components/generating/generating.css";

// W0.5 (founder amendment, 2026-08-17): the gallery rides along as
// presentation-only chrome — the tab and the gallery surface render with the
// artifact list the caller passes (empty until the W1.3 read seam), never
// fixture data. The chat surface stays out; `surface` here is the editor pair
// only (artifact | gallery).

export function ArtifactStage({
  activeArtifactId,
  activeDocumentId,
  activePageId,
  artifacts,
  artifactKind,
  canvasControlsRef,
  canvasReloadToken,
  agentWorking = false,
  artifactMaximized,
  artifactTitle,
  editDisabled,
  editDisabledReason,
  editing,
  exportPreview,
  exportStatus,
  generating,
  onActivateArtifact,
  onCanvasSelect,
  onCloneTextCommit,
  onRequestExportPreview,
  onRichTextCommit,
  onRichTextSessionChange,
  richTextBusy,
  richTextEnabled,
  richTextTheme,
  onAddAccountsToChat,
  onCloseArtifact,
  onOpenGallery,
  onOpenTargetAccounts,
  documentTabs,
  canEditDocuments = false,
  panelOpen = true,
  onOpenGalleryArtifact,
  onPageChange,
  pages,
  publishLocked = false,
  onRenameArtifact,
  onRenameArtifactFor,
  onSceneChange,
  onSceneDropImageFiles,
  onSceneEngineStatusChange,
  onSceneFitZoom,
  onSceneLockedEdit,
  onSceneHistoryChange,
  onSceneGestureZoom,
  onSceneAppliedOperations,
  onSceneOperations,
  annotations,
  onSceneSelect,
  onSceneZoomChange,
  sceneCanvasControlsRef,
  sceneDisplayScene,
  sceneGestureDisabled,
  scenePalette,
  sceneSelectedNodeId,
  sceneZoomLabel,
  sceneZoomOverride,
  onToggleMaximized,
  onTogglePanel,
  onToggleEditing,
  openArtifacts,
  overlay,
  projectTitle,
  projectId,
  redoDisabled,
  selectedCanvasNodeId,
  surface,
  targetAccountsBusy,
  targetAccountsRefreshToken,
  undoDisabled,
}: {
  activeArtifactId: string | null;
  /** W2.1: the active artifact's design-document id (the W1.3 read seam).
   * Present → the web canvas mounts the real sandboxed render; absent → the
   * dummy's empty canvas (geometry stable). */
  activeDocumentId?: string | null;
  /** F5 task 18: which page of a multi-page web document the canvas renders —
   * owned by the web editing session (it also owns the document and the
   * selection). Absent → the render seam picks the document's own first page,
   * exactly as it did before the switcher existed. */
  activePageId?: string | null;
  /** Slice 2 (R-A1): the web canvas's annotation session — the comment box a
   * click opens and the numbered badges it draws back into the frame. */
  annotations?: WebAnnotationsCanvasBinding;
  artifacts: ProjectArtifact[];
  /** W2.3: receives the mounted web canvas's imperative controls
   * (`selectNode` for layer-row clicks). */
  canvasControlsRef?: RefObject<WebArtifactCanvasControls | null>;
  /** W3.2: bumped after a committed write to refetch the render. */
  canvasReloadToken?: number;
  /** The persisted canvas selection, re-sent to the frame after a render
   * rebuild (outline survival across writes). */
  selectedCanvasNodeId?: string | null;
  artifactKind: ChatShellArtifactKind | null;
  artifactMaximized: boolean;
  artifactTitle: string;
  /** Scene-ad motion (2026-09-04 port): true while the agent-run lock holds
   * over this ad — `chat-surface.tsx`'s `sceneLocked`. The standalone artifact
   * route has no turn stream and leaves it unset. */
  agentWorking?: boolean;
  /** Task 4: the agent-run lock refuses ENTRY into edit mode (never the exit).
   * Absent leaves the header's Edit button exactly as it is today. */
  editDisabled?: boolean;
  /** Task 4: why, in the lock's own ratified words. */
  editDisabledReason?: string | null;
  editing: boolean;
  /** AD4.D step 3 (§1.11): the ad editing session's render for the export
   * menu's designed preview region, with the element that hosts it. Absent
   * leaves that region the designed empty state it is today. */
  exportPreview?: ImageExportPreview | null;
  /** AD4.D step 2 (§1.11): the ad editing session's export outcome, on its way
   * to the export menu's status line. Absent leaves the menu announcing
   * its controller's own optimistic line, exactly as it does today. */
  exportStatus?: SceneExportStatus | null;
  /** An agent turn is in flight on this thread's open design leg — the arming
   * signal for the WEBSITE pane's generating veil (the stage owns the hold rule
   * that decides when it lifts). The ad branch reads nothing: the ad lock is not
   * integrated (founder ruling, 2026-09-07). Passed by the chats route only —
   * the standalone artifact route has no turn stream, the same posture as
   * `sceneGestureDisabled` below. */
  generating?: boolean;
  onActivateArtifact: (artifactId: string) => void;
  /** AD4.D step 3: the export menu asking the ad session to render the settings
   * it is showing. Absent keeps the menu's preview effect inert. */
  onRequestExportPreview?: (
    format: ImageExportFormat,
    scale: ImageExportScale,
  ) => void;
  /** W2.2: nonce-validated selection events from the web canvas bridge. */
  onCanvasSelect?: (selection: WebSelection | null) => void;
  /** W4.8a: a text node's in-iframe rich-text session committed. */
  onRichTextCommit?: (nodeId: string, content: RichTextDocument) => void;
  /** Slice 3 (R-A6): the in-frame clone text editor committed — the session
   * persists ONE `set_fragment_text_override` op. */
  onCloneTextCommit?: (
    address: WebElementAddress,
    override: WebFragmentTextOverride,
  ) => void;
  /** W4.8a: the rich-text session state, mirrored up on every change. */
  onRichTextSessionChange?: (state: WebRichTextSessionState) => void;
  /** W4.8a: a write is already in flight — the toolbar disables itself. */
  richTextBusy?: boolean;
  /** W4.8a: the editing gate — falsy keeps the render read-only. */
  richTextEnabled?: boolean;
  /** W4.8a: the document's compiled theme, for the toolbar's color panels. */
  richTextTheme?: WebTheme | null;
  onCloseArtifact: (artifactId: string) => void;
  onOpenGallery: () => void;
  /** The Target accounts tab's handler. Optional (the branch's stage makes it
   * required) because the ARTIFACT route mounts this same stage with no
   * project in hand — absent, the tab is simply not rendered, which is the
   * same gate the branch expresses through `projectId`. */
  onOpenTargetAccounts?: () => void;
  documentTabs?: ReturnType<typeof useProjectDocumentTabs>;
  canEditDocuments?: boolean;
  panelOpen?: boolean;
  /** The Target accounts tab's "Add to chat" (founder request 2026-09-11):
   * prepares the selected accounts against the open chat and lands them in
   * its composer. Absent when no chat is in hand (the artifact route, fixture
   * transport, a workspace without context refs) — the button is not shown. */
  onAddAccountsToChat?: (contextRefs: readonly ChatContextRef[]) => Promise<boolean>;
  onOpenGalleryArtifact: (artifact: GalleryArtifact) => void;
  /** F5 task 18: the header's switcher reporting the page the user picked,
   * back to the web editing session that owns it. */
  onPageChange?: (pageId: string) => void;
  /** F5 task 18: the active web document's pages, for that switcher. */
  pages?: readonly ArtifactPageOption[];
  /** Task 28 (founder 2026-10-13): a design run is working on this website, so
   * the Share menu's Publish waits — `chat-surface.tsx`'s `publishLocked` (off
   * the turn stream), or the standalone artifact route's document-scoped
   * agent-busy poll (`editor-surface.tsx`). Absent leaves publishing as it is. */
  publishLocked?: boolean;
  onRenameArtifact: (title: string) => void;
  onRenameArtifactFor: (artifactId: string, title: string) => void;
  /** AD2.7: the rendered ad scene, mirrored up for the shared editing
   * session's hydration + layer tree (one document fetch, one engine). */
  onSceneChange?: (
    scene: Scene | null,
    pageId: PageId | null,
    documentId: string,
  ) => void;
  /** Clipboard Task 8: image files dropped on the ad canvas, with the page
   * point the pointer named. Passed straight through to the canvas. */
  onSceneDropImageFiles?: (
    files: File[],
    pagePoint: { x: number; y: number },
  ) => void;
  /** AD2.3: the ad canvas's wasm stamp-handshake outcome, mirrored upward so
   * the shell can refuse edits (and, post Gate G-D, explain why). */
  onSceneEngineStatusChange?: (status: SceneEngineStatus) => void;
  /** AD2.3: the ad canvas's fit-on-open zoom, as one of the header menu's own
   * 5% steps (§1.10) — AD2.8 shows it in the menu until the user chooses. */
  onSceneFitZoom?: (zoom: string) => void;
  /** Task 4: the ad canvas refused a gesture or a caret because the agent-run
   * lock holds, and is asking the shell to say so. Absent → nothing is said,
   * which is the artifact route's own (lockless) posture. */
  onSceneLockedEdit?: () => void;
  /** AD3.3: the loaded ad document's undo/redo stack depths, mirrored up so the
   * header's two history rows disable off the server's real stacks. The
   * committed version rides along so the session can stamp edit-target
   * submissions after the canvas unmounts. */
  onSceneHistoryChange?: (
    history: SceneDocumentHistory,
    documentId: string,
    currentVersion: number | null,
  ) => void;
  /** AD2.10: where a pan/wheel gesture left the viewport — the header's zoom
   * control displays this over both the fit and the chosen step, because after
   * a pinch it is the only one of the three that is true. Null when the canvas
   * falls back to the derived viewport. */
  onSceneGestureZoom?: (zoom: string | null) => void;
  /** AD4.C / Ruling C-3: a committed canvas gesture's operations, on their way
   * to the ad session's own `applyOps` — the SAME write path the inspector
   * commits through, so a drag lands as one atomic batch and one undo frame. */
  onSceneOperations?: (operations: Operation[], intent?: string) => boolean;
  /** AD4.C-3 / Ruling C-12: operations the ad canvas's engine has ALREADY
   * applied (the freeze-on-grab), on their way to the session's persist-only
   * seam. A deliberate sibling of `onSceneOperations` rather than a flag on it:
   * routing an already-applied batch through the ordinary write path would
   * apply it twice. */
  onSceneAppliedOperations?: (operations: Operation[], scene: Scene) => boolean;
  /** AD2.7: a press on the ad canvas resolved to the node it selects (§5's
   * nearest representable ancestor), or null for a press on nothing. */
  onSceneSelect?: (nodeId: string | null) => void;
  /** AD2.8: the user picked a step from the ad header's zoom menu. */
  onSceneZoomChange?: (zoom: string) => void;
  /** AD2.3: receives the mounted ad canvas's imperative controls (hit-testing
   * for AD2.5's selection, refresh, and the rendered scene). */
  sceneCanvasControlsRef?: RefObject<SceneCanvasControls | null>;
  /** Task 9 (scene live-streaming rung B): the reveal pump's held scene — what
   * the ad canvas draws INSTEAD of the loaded document while a design agent is
   * streaming operations into it. Null (and on every route but the locked chat
   * surface) the canvas renders the document, exactly as it does today. */
  sceneDisplayScene?: Scene | null;
  /** AD4.C / GATE G-H: an agent turn is in flight, so on-canvas drag and
   * resize are off and the corner handles are not drawn. Selection stays live.
   * Passed by the chats route only — the artifact route has no turn stream to
   * read (the same posture as `inspectorDisabled` there). */
  sceneGestureDisabled?: boolean;
  /** Rung C / §1.6: the document's brand-kit colour vocabulary, for the caret
   * session's formatting toolbar — the same `sceneSession.palette` the
   * inspector's colour pickers are handed, so one document has one palette. */
  scenePalette?: ScenePalette | null;
  /** AD2.7: the session's primary selection, back down to the canvas. */
  sceneSelectedNodeId?: string | null;
  /**
   * AD2.8/§1.10: the two halves of one zoom, deliberately separate.
   *
   * `sceneZoomLabel` is what the HEADER MENU shows — the chosen step, or the
   * fit snapped to the nearest step the menu offers. `sceneZoomOverride` is
   * what the CANVAS applies, and it is null until the user actually chooses,
   * so an untouched artifact keeps its EXACT contain-fit (ruling 17) rather
   * than the rounded label.
   */
  sceneZoomLabel?: string | null;
  sceneZoomOverride?: string | null;
  onToggleMaximized: () => void;
  onTogglePanel: () => void;
  onToggleEditing: () => void;
  openArtifacts: ChatShellOpenArtifact[];
  /** Replace-image Task 6: chrome the surfaces float over the stage (today the
   * asset-library picker). Pass-through only — this component owns no part of
   * what it renders, exactly as `onSceneDropImageFiles` owns no part of a drop. */
  overlay?: ReactNode;
  projectTitle?: string;
  /** The project the Target accounts surface is scoped to. Absent (the
   * artifact route) → no tab and no surface. */
  projectId?: string;
  /** W3.4: empty-stack disables for the action menu's Undo/Redo. */
  redoDisabled?: boolean;
  surface: EditorShellSurface;
  /** True while the project's discovery run is live: the Target accounts tab label spins. */
  targetAccountsBusy?: boolean;
  /** Bumped on every discovery poll read: the tab refetches its rows (spec 2026-09-12 §3). */
  targetAccountsRefreshToken?: number;
  undoDisabled?: boolean;
}) {
  const showingArtifact = surface === "artifact" && artifactKind !== null;
  // The header's device menu, made real (ported from the source dev shell's
  // width chips, WebEditorApp.tsx `WidthMode`): the choice pins the web
  // canvas to one of the engine's canonical viewport layers, so the page's
  // actual md:/lg: breakpoints kick in. Owned HERE — the stage renders both
  // the menu (header) and the viewport it drives — and per-stage-session
  // only: presentation state, nothing persisted.
  const [previewDevice, setPreviewDevice] =
    useState<ArtifactPreviewDevice>("Desktop");
  const webCanvasClass = [
    styles.webCanvas,
    // `.clue-gen-host` (generating.css) supplies the positioning context and
    // the stacking root the veil and the glow need — both are
    // `position: absolute; inset: 0` inside it. It goes on the wrapper that
    // renders WHETHER OR NOT a document is open, which is the whole point of
    // hosting here (see the mount below).
    "clue-gen-host",
    previewDevice === "Tablet" ? styles.webCanvasTablet : "",
    previewDevice === "Mobile" ? styles.webCanvasMobile : "",
  ]
    .filter(Boolean)
    .join(" ");

  // The website pane's "agent is generating" motion (cofounder handoff
  // ad4f30bb), hosted HERE rather than inside `WebArtifactCanvas` — founder
  // ruling, 2026-09-07 (the handover's done-when #1). On the very first landing
  // page there is no web document yet, so the canvas is not mounted at all; a
  // veil living inside it could not appear until the artifact was born, which
  // is precisely when the user stops needing it. This wrapper is always here.
  //
  // The canvas reports its render state up (`onRenderKindChange`) and the hold
  // rule lives on this side. With no document open there is no canvas to report
  // anything, and an absent page IS the empty state — so `empty` is both the
  // seed and the derived answer, which also means a closed artifact can never
  // strand the veil on a stale `loading` from the document before it.
  const [renderKind, setRenderKind] = useState<VeilRenderKind>("empty");
  const effectiveKind: VeilRenderKind = activeDocumentId ? renderKind : "empty";
  // React's own adjust-state-on-prop-change (a render-time comparison, the
  // pattern `scene-artifact-canvas.tsx` and `use-scene-manual-edits.ts` already
  // use), never a setState in an effect: this repo's react-hooks lint bars that,
  // and an effect would paint one frame of the stale answer first. The reducer
  // returns its own previous object when nothing moved, which is what makes
  // this converge.
  const [veil, setVeil] = useState(initialVeilState);
  const nextVeil = nextVeilState(veil, {
    generating: generating ?? false,
    reloadToken: canvasReloadToken ?? 0,
    renderKind: effectiveKind,
    documentId: activeDocumentId ?? null,
  });
  if (nextVeil !== veil) setVeil(nextVeil);
  // The motion is the WEBSITE half only (web or site): the ad lock is not
  // integrated (founder ruling, 2026-09-07), so the ad branch mounts nothing.
  const veilActive = isWebsiteKind(artifactKind) && nextVeil.active;
  // AD2.10: a mounted ad canvas owns the whole stage as its viewport; the
  // designed empty state keeps the centred card.
  const adStageClass = activeDocumentId
    ? styles.sceneOutputStage
    : styles.imageOutputStage;
  // 2026-09-04 port: one boolean drives both halves of the co-founder's
  // agent-working motion — the lock's chip and the edge glow.
  const sceneMotion = sceneAgentMotionActive({
    agentWorking,
    hasScene: Boolean(activeDocumentId),
  });

  return (
    <section aria-label="Artifact workspace" className={styles.artifactWorkspace}>
      <ArtifactTabs
        activeArtifactId={activeArtifactId}
        artifactMaximized={artifactMaximized}
        artifacts={openArtifacts}
        galleryTabVisible
        onActivateArtifact={onActivateArtifact}
        onCloseArtifact={onCloseArtifact}
        onOpenGallery={onOpenGallery}
        onOpenTargetAccounts={projectId ? onOpenTargetAccounts : undefined}
        documentTabs={documentTabs}
        onRenameArtifact={onRenameArtifactFor}
        onToggleMaximized={onToggleMaximized}
        onTogglePanel={onTogglePanel}
        surface={surface}
        targetAccountsBusy={targetAccountsBusy}
      />
      {projectId ? (
        <div className={styles.workspaceSurface} hidden={surface !== "target-accounts"}>
          <ProjectTargetAccounts active={surface === "target-accounts"} key={projectId} onAddToChat={onAddAccountsToChat} projectId={projectId} projectTitle={projectTitle ?? "Project"} refreshToken={targetAccountsRefreshToken} />
        </div>
      ) : null}
      {projectId && documentTabs ? documentTabs.visited.map((path) => (
        <div key={path} className={styles.workspaceSurface} hidden={surface !== "plan" || documentTabs.selectedPath !== path}>
          <ProjectDocumentSurface active={panelOpen && surface === "plan" && documentTabs.selectedPath === path} canWrite={canEditDocuments} projectId={projectId} list={documentTabs.list} documentPath={path} />
        </div>
      )) : null}
      {showingArtifact ? (
        <>
          <ArtifactHeader
            editDisabled={editDisabled}
            editDisabledReason={editDisabledReason}
            activePageId={activePageId}
            device={previewDevice}
            documentId={activeDocumentId}
            editing={editing}
            exportPreview={exportPreview}
            exportStatus={exportStatus}
            kind={artifactKind}
            onDeviceChange={setPreviewDevice}
            onEdit={onToggleEditing}
            onPageChange={onPageChange}
            onRename={onRenameArtifact}
            pages={pages}
            publishLocked={publishLocked}
            onRequestExportPreview={onRequestExportPreview}
            onZoomChange={onSceneZoomChange}
            redoDisabled={redoDisabled}
            title={artifactTitle}
            undoDisabled={undoDisabled}
            zoom={sceneZoomLabel}
          />
          <div className={`${styles.outputStage} ${artifactKind === "ad" ? adStageClass : styles.webOutputStage}`}>
            {artifactKind !== "ad" ? (
              <div
                aria-label={
                  artifactKind === "web" && activeDocumentId ? "Web output canvas" : "Empty web output canvas"
                }
                className={webCanvasClass}
              >
                {artifactKind === "web" && activeDocumentId ? (
                  <WebArtifactCanvas
                    annotations={annotations}
                    controlsRef={canvasControlsRef}
                    documentId={activeDocumentId}
                    editing={editing}
                    onRenderKindChange={setRenderKind}
                    /* F5 task 20: a site-internal link clicked inside the
                     * canvas switches the page through the very same session
                     * setter the header's switcher uses — one active page, one
                     * writer, so the two surfaces can never disagree. */
                    onCloneTextCommit={onCloneTextCommit}
                    onNavigate={onPageChange}
                    onRichTextCommit={onRichTextCommit}
                    onRichTextSessionChange={onRichTextSessionChange}
                    onSelect={onCanvasSelect}
                    pageId={activePageId ?? undefined}
                    reloadToken={canvasReloadToken}
                    richTextBusy={richTextBusy}
                    richTextEnabled={richTextEnabled}
                    richTextTheme={richTextTheme}
                    selectedNodeId={selectedCanvasNodeId}
                  />
                ) : null}
                {/* Veil under glow (z-6 < z-7, per the delivered sheet), both
                 * after the canvas so they sit over whatever it is showing —
                 * the previous page, the loading frame, the error frame, or the
                 * designed empty state on a first request.
                 *
                 * INTERACTION: an INACTIVE veil is `pointer-events: none` in
                 * the sheet (`.clue-gen-veil` sets it; only
                 * `[data-active="true"]` restores `pointer-events: auto`), so
                 * between turns it cannot intercept a click, a hover, or a
                 * double-click — Edit-mode annotations, the comment box, and the
                 * in-frame text editors all reach the iframe untouched. While a
                 * turn IS running the veil deliberately swallows input over the
                 * pane. The glow is decorative and `pointer-events: none` in
                 * both states. */}
                <WebsiteGeneratingVeil active={veilActive} />
                <GeneratingGlow active={veilActive} />
              </div>
            ) : activeDocumentId ? (
              /* AD2.10 (founder ruling, 2026-08-20): the mounted scene canvas
               * IS the stage — an infinite workspace with the artboard floating
               * on it — so it is no longer wrapped in the dummy's fixed
               * `.imageCanvas` card, which could only ever show a 640px square
               * of it. The card keeps the empty state below, unchanged. */
              <div
                aria-label="Ad output canvas"
                className={`${styles.sceneStage} clue-gen-host`}
              >
                <SceneArtifactCanvas
                  controlsRef={sceneCanvasControlsRef}
                  displayScene={sceneDisplayScene}
                  documentId={activeDocumentId}
                  gestureDisabled={sceneGestureDisabled}
                  onLockedEdit={onSceneLockedEdit}
                  onDropImageFiles={onSceneDropImageFiles}
                  onEngineStatusChange={onSceneEngineStatusChange}
                  onFitZoom={onSceneFitZoom}
                  onGestureZoom={onSceneGestureZoom}
                  onHistoryChange={onSceneHistoryChange}
                  onAppliedOperations={onSceneAppliedOperations}
                  onOperations={onSceneOperations}
                  onSceneChange={onSceneChange}
                  onSelect={onSceneSelect}
                  palette={scenePalette}
                  reloadToken={canvasReloadToken}
                  selectedNodeId={sceneSelectedNodeId}
                  zoom={sceneZoomOverride}
                />
                {/* The co-founder's agent-working motion (handoff 2026-09-04):
                    the artwork stays visible and keeps updating live; a
                    transparent shield swallows canvas input and a chip with the
                    Clue-mark spinner says the agent is mid-edit; a thin light
                    frame drifts round the stage's edges. Both fade on their own
                    when `active` drops — they stay mounted so the exit
                    transition can play. Stacking is theirs (42/43), above the
                    canvas's banners and caret. */}
                <AdDesigningLock active={sceneMotion} />
                <GeneratingGlow active={sceneMotion} />
              </div>
            ) : (
              <div
                aria-label="Empty ad output canvas"
                className={styles.imageCanvas}
              />
            )}
          </div>
        </>
      ) : null}
      <div
        className={styles.workspaceSurface}
        hidden={showingArtifact || surface === "target-accounts" || surface === "plan"}
      >
        <ProjectGallery
          artifacts={artifacts}
          documents={documentTabs?.list.documents}
          documentsLoading={documentTabs?.list.loading || documentTabs?.opening}
          documentsError={documentTabs?.list.error || documentTabs?.error}
          onRetryDocuments={documentTabs?.list.reload}
          onOpenArtifact={onOpenGalleryArtifact}
          projectTitle={projectTitle}
        />
      </div>
      {overlay}
    </section>
  );
}
