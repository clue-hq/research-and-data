import type {
  ChatShellArtifactKind,
  ChatShellOpenArtifact,
} from "../model/chat-shell";
import {
  WebArtifactCanvas,
  type WebArtifactCanvasControls,
  type WebRichTextSessionState,
} from "@/features/design-editor/components/web-artifact-canvas";
import {
  SceneArtifactCanvas,
  type SceneCanvasControls,
} from "@/features/design-editor/components/scene-artifact-canvas";
import type { SceneEngineStatus } from "@/features/design-editor/hooks/use-scene-document";
import type { WebSelection } from "@/features/design-editor/engine/webBridge";
import type {
  RichTextDocument,
  WebTheme,
} from "@/features/design-editor/engine/webDocuments";
import type { RefObject } from "react";
import { ProjectGallery } from "@/features/gallery/components/project-gallery";
import type { GalleryArtifact } from "@/features/gallery/model/project-gallery";
import type { ProjectArtifact } from "@/features/projects/model/project-workspace";
import type { EditorShellSurface } from "../hooks/use-editor-shell-controller";
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
  artifacts,
  artifactKind,
  canvasControlsRef,
  canvasReloadToken,
  artifactMaximized,
  artifactTitle,
  editing,
  onActivateArtifact,
  onCanvasSelect,
  onRichTextCommit,
  onRichTextSessionChange,
  richTextBusy,
  richTextEnabled,
  richTextTheme,
  onCloseArtifact,
  onOpenGallery,
  onOpenGalleryArtifact,
  onRenameArtifact,
  onRenameArtifactFor,
  onSceneEngineStatusChange,
  onSceneFitZoom,
  sceneCanvasControlsRef,
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
  onActivateArtifact: (artifactId: string) => void;
  /** W2.2: nonce-validated selection events from the web canvas bridge. */
  onCanvasSelect?: (selection: WebSelection | null) => void;
  /** W4.8a: a text node's in-iframe rich-text session committed. */
  onRichTextCommit?: (nodeId: string, content: RichTextDocument) => void;
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
  onRenameArtifact: (title: string) => void;
  onRenameArtifactFor: (artifactId: string, title: string) => void;
  /** AD2.3: the ad canvas's wasm stamp-handshake outcome, mirrored upward so
   * the shell can refuse edits (and, post Gate G-D, explain why). */
  onSceneEngineStatusChange?: (status: SceneEngineStatus) => void;
  /** AD2.3: the ad canvas's fit-on-open zoom, as one of the header menu's own
   * 5% steps (§1.10). AD2.8 binds it to the menu. */
  onSceneFitZoom?: (zoom: string) => void;
  /** AD2.3: receives the mounted ad canvas's imperative controls (hit-testing
   * for AD2.5's selection, refresh, and the rendered scene). */
  sceneCanvasControlsRef?: RefObject<SceneCanvasControls | null>;
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
            editing={editing}
            kind={artifactKind}
            onEdit={onToggleEditing}
            onRename={onRenameArtifact}
            redoDisabled={redoDisabled}
            title={artifactTitle}
            undoDisabled={undoDisabled}
          />
          <div className={`${styles.outputStage} ${artifactKind === "ad" ? styles.imageOutputStage : styles.webOutputStage}`}>
            {artifactKind === "web" ? (
              <div
                aria-label={
                  activeDocumentId ? "Web output canvas" : "Empty web output canvas"
                }
                className={styles.webCanvas}
              >
                {activeDocumentId ? (
                  <WebArtifactCanvas
                    controlsRef={canvasControlsRef}
                    documentId={activeDocumentId}
                    editing={editing}
                    onRichTextCommit={onRichTextCommit}
                    onRichTextSessionChange={onRichTextSessionChange}
                    onSelect={onCanvasSelect}
                    reloadToken={canvasReloadToken}
                    richTextBusy={richTextBusy}
                    richTextEnabled={richTextEnabled}
                    richTextTheme={richTextTheme}
                    selectedNodeId={selectedCanvasNodeId}
                  />
                ) : null}
              </div>
            ) : (
              <div
                aria-label={
                  activeDocumentId ? "Ad output canvas" : "Empty ad output canvas"
                }
                className={styles.imageCanvas}
              >
                {/* AD2.3: the real scene renders inside the dummy's artboard
                 * card — same shape as the web branch above, and the card's
                 * geometry is untouched (the canvas fills it). */}
                {activeDocumentId ? (
                  <SceneArtifactCanvas
                    controlsRef={sceneCanvasControlsRef}
                    documentId={activeDocumentId}
                    onEngineStatusChange={onSceneEngineStatusChange}
                    onFitZoom={onSceneFitZoom}
                    reloadToken={canvasReloadToken}
                  />
                ) : null}
              </div>
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
