import type {
  ChatShellArtifactKind,
  ChatShellOpenArtifact,
} from "../model/chat-shell";
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
  artifacts,
  artifactKind,
  artifactMaximized,
  artifactTitle,
  editing,
  onActivateArtifact,
  onCloseArtifact,
  onOpenGallery,
  onOpenGalleryArtifact,
  onRenameArtifact,
  onRenameArtifactFor,
  onToggleMaximized,
  onTogglePanel,
  onToggleEditing,
  openArtifacts,
  projectTitle,
  surface,
}: {
  activeArtifactId: string | null;
  artifacts: ProjectArtifact[];
  artifactKind: ChatShellArtifactKind | null;
  artifactMaximized: boolean;
  artifactTitle: string;
  editing: boolean;
  onActivateArtifact: (artifactId: string) => void;
  onCloseArtifact: (artifactId: string) => void;
  onOpenGallery: () => void;
  onOpenGalleryArtifact: (artifact: GalleryArtifact) => void;
  onRenameArtifact: (title: string) => void;
  onRenameArtifactFor: (artifactId: string, title: string) => void;
  onToggleMaximized: () => void;
  onTogglePanel: () => void;
  onToggleEditing: () => void;
  openArtifacts: ChatShellOpenArtifact[];
  projectTitle?: string;
  surface: EditorShellSurface;
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
            title={artifactTitle}
          />
          <div className={`${styles.outputStage} ${artifactKind === "ad" ? styles.imageOutputStage : styles.webOutputStage}`}>
            <div
              aria-label={artifactKind === "web" ? "Empty web output canvas" : "Empty ad output canvas"}
              className={artifactKind === "web" ? styles.webCanvas : styles.imageCanvas}
            />
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
