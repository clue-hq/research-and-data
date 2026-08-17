import type {
  ChatShellArtifactKind,
  ChatShellOpenArtifact,
} from "../model/chat-shell";
import { ArtifactHeader } from "./artifact-header";
import { ArtifactTabs } from "./artifact-tabs";
import styles from "./chat-shell.module.css";

// Gallery severed per founder ruling (website-editor scope): the stage renders
// only when an artifact is active — no gallery else-branch, no gallery tab
// (prop-gated off in ArtifactTabs). The chat/gallery surface machine is gone
// with it; this stage always lives on the artifact surface.

export function ArtifactStage({
  activeArtifactId,
  artifactKind,
  artifactMaximized,
  artifactTitle,
  editing,
  onActivateArtifact,
  onCloseArtifact,
  onRenameArtifact,
  onRenameArtifactFor,
  onToggleMaximized,
  onTogglePanel,
  onToggleEditing,
  openArtifacts,
}: {
  activeArtifactId: string | null;
  artifactKind: ChatShellArtifactKind | null;
  artifactMaximized: boolean;
  artifactTitle: string;
  editing: boolean;
  onActivateArtifact: (artifactId: string) => void;
  onCloseArtifact: (artifactId: string) => void;
  onRenameArtifact: (title: string) => void;
  onRenameArtifactFor: (artifactId: string, title: string) => void;
  onToggleMaximized: () => void;
  onTogglePanel: () => void;
  onToggleEditing: () => void;
  openArtifacts: ChatShellOpenArtifact[];
}) {
  const showingArtifact = artifactKind !== null;

  return (
    <section aria-label="Artifact workspace" className={styles.artifactWorkspace}>
      <ArtifactTabs
        activeArtifactId={activeArtifactId}
        artifactMaximized={artifactMaximized}
        artifacts={openArtifacts}
        galleryTabVisible={false}
        onActivateArtifact={onActivateArtifact}
        onCloseArtifact={onCloseArtifact}
        onRenameArtifact={onRenameArtifactFor}
        onToggleMaximized={onToggleMaximized}
        onTogglePanel={onTogglePanel}
        surface="artifact"
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
      ) : null}
    </section>
  );
}
