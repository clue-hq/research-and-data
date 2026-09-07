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
import type {
  WebElementAddress,
  WebSelection,
} from "@/features/design-editor/engine/webBridge";
import type {
  RichTextDocument,
  WebFragmentTextOverride,
  WebTheme,
} from "@/features/design-editor/engine/webDocuments";
import { useState, type RefObject } from "react";
import { ProjectGallery } from "@/features/gallery/components/project-gallery";
import type { GalleryArtifact } from "@/features/gallery/model/project-gallery";
import type { ProjectArtifact } from "@/features/projects/model/project-workspace";
import type { EditorShellSurface } from "../hooks/use-editor-shell-controller";
import type {
  ArtifactPageOption,
  ArtifactPreviewDevice,
} from "../hooks/use-artifact-toolbar-controller";
import { ArtifactHeader } from "./artifact-header";
import { ArtifactTabs } from "./artifact-tabs";
import styles from "./chat-shell.module.css";

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
  artifactMaximized,
  artifactTitle,
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
  onCloseArtifact,
  onOpenGallery,
  onOpenGalleryArtifact,
  onPageChange,
  pages,
  onRenameArtifact,
  onRenameArtifactFor,
  onSceneChange,
  onSceneEngineStatusChange,
  onSceneFitZoom,
  onSceneHistoryChange,
  onSceneGestureZoom,
  onSceneAppliedOperations,
  onSceneOperations,
  annotations,
  onSceneSelect,
  onSceneZoomChange,
  sceneCanvasControlsRef,
  sceneGestureDisabled,
  sceneSelectedNodeId,
  sceneZoomLabel,
  sceneZoomOverride,
  onToggleMaximized,
  onTogglePanel,
  onToggleEditing,
  openArtifacts,
  projectTitle,
  redoDisabled,
  selectedCanvasNodeId,
  surface,
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
  editing: boolean;
  /** AD4.D step 3 (§1.11): the ad editing session's render for the export
   * menu's designed preview region, with the element that hosts it. Absent
   * leaves that region the designed empty state it is today. */
  exportPreview?: ImageExportPreview | null;
  /** AD4.D step 2 (§1.11): the ad editing session's export outcome, on its way
   * to the export menu's status line. Absent leaves the menu announcing
   * its controller's own optimistic line, exactly as it does today. */
  exportStatus?: SceneExportStatus | null;
  /** An agent turn is in flight on this thread's open design leg. The WEB canvas
   * raises its generating veil over the pane; nothing else in the stage reads
   * it. Passed by the chats route only — the standalone artifact route has no
   * turn stream, the same posture as `sceneGestureDisabled` below. */
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
  onOpenGalleryArtifact: (artifact: GalleryArtifact) => void;
  /** F5 task 18: the header's switcher reporting the page the user picked,
   * back to the web editing session that owns it. */
  onPageChange?: (pageId: string) => void;
  /** F5 task 18: the active web document's pages, for that switcher. */
  pages?: readonly ArtifactPageOption[];
  onRenameArtifact: (title: string) => void;
  onRenameArtifactFor: (artifactId: string, title: string) => void;
  /** AD2.7: the rendered ad scene, mirrored up for the shared editing
   * session's hydration + layer tree (one document fetch, one engine). */
  onSceneChange?: (
    scene: Scene | null,
    pageId: PageId | null,
    documentId: string,
  ) => void;
  /** AD2.3: the ad canvas's wasm stamp-handshake outcome, mirrored upward so
   * the shell can refuse edits (and, post Gate G-D, explain why). */
  onSceneEngineStatusChange?: (status: SceneEngineStatus) => void;
  /** AD2.3: the ad canvas's fit-on-open zoom, as one of the header menu's own
   * 5% steps (§1.10) — AD2.8 shows it in the menu until the user chooses. */
  onSceneFitZoom?: (zoom: string) => void;
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
  /** AD4.C / GATE G-H: an agent turn is in flight, so on-canvas drag and
   * resize are off and the corner handles are not drawn. Selection stays live.
   * Passed by the chats route only — the artifact route has no turn stream to
   * read (the same posture as `inspectorDisabled` there). */
  sceneGestureDisabled?: boolean;
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
  projectTitle?: string;
  /** W3.4: empty-stack disables for the action menu's Undo/Redo. */
  redoDisabled?: boolean;
  surface: EditorShellSurface;
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
    previewDevice === "Tablet" ? styles.webCanvasTablet : "",
    previewDevice === "Mobile" ? styles.webCanvasMobile : "",
  ]
    .filter(Boolean)
    .join(" ");
  // AD2.10: a mounted ad canvas owns the whole stage as its viewport; the
  // designed empty state keeps the centred card.
  const adStageClass = activeDocumentId
    ? styles.sceneOutputStage
    : styles.imageOutputStage;

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
        onRenameArtifact={onRenameArtifactFor}
        onToggleMaximized={onToggleMaximized}
        onTogglePanel={onTogglePanel}
        surface={surface}
      />
      {showingArtifact ? (
        <>
          <ArtifactHeader
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
            onRequestExportPreview={onRequestExportPreview}
            onZoomChange={onSceneZoomChange}
            redoDisabled={redoDisabled}
            title={artifactTitle}
            undoDisabled={undoDisabled}
            zoom={sceneZoomLabel}
          />
          <div className={`${styles.outputStage} ${artifactKind === "ad" ? adStageClass : styles.webOutputStage}`}>
            {artifactKind === "web" ? (
              <div
                aria-label={
                  activeDocumentId ? "Web output canvas" : "Empty web output canvas"
                }
                className={webCanvasClass}
              >
                {activeDocumentId ? (
                  <WebArtifactCanvas
                    annotations={annotations}
                    controlsRef={canvasControlsRef}
                    documentId={activeDocumentId}
                    editing={editing}
                    generating={generating}
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
              </div>
            ) : activeDocumentId ? (
              /* AD2.10 (founder ruling, 2026-08-20): the mounted scene canvas
               * IS the stage — an infinite workspace with the artboard floating
               * on it — so it is no longer wrapped in the dummy's fixed
               * `.imageCanvas` card, which could only ever show a 640px square
               * of it. The card keeps the empty state below, unchanged. */
              <div aria-label="Ad output canvas" className={styles.sceneStage}>
                <SceneArtifactCanvas
                  controlsRef={sceneCanvasControlsRef}
                  documentId={activeDocumentId}
                  gestureDisabled={sceneGestureDisabled}
                  onEngineStatusChange={onSceneEngineStatusChange}
                  onFitZoom={onSceneFitZoom}
                  onGestureZoom={onSceneGestureZoom}
                  onHistoryChange={onSceneHistoryChange}
                  onAppliedOperations={onSceneAppliedOperations}
                  onOperations={onSceneOperations}
                  onSceneChange={onSceneChange}
                  onSelect={onSceneSelect}
                  reloadToken={canvasReloadToken}
                  selectedNodeId={sceneSelectedNodeId}
                  zoom={sceneZoomOverride}
                />
              </div>
            ) : (
              <div
                aria-label="Empty ad output canvas"
                className={styles.imageCanvas}
              />
            )}
          </div>
        </>
      ) : (
        <ProjectGallery
          artifacts={artifacts}
          onOpenArtifact={onOpenGalleryArtifact}
          projectTitle={projectTitle}
        />
      )}
    </section>
  );
}
