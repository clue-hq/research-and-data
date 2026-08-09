import { ProjectIcon } from "./project-icon";
import styles from "./project-flow.module.css";

export function ArtifactWorkspace({
  controller,
}: {
  controller: ReturnType<
    typeof import("../hooks/use-project-workspace-controller").useProjectWorkspaceController
  >;
}) {
  return (
    <section className={styles.artifactWorkspace}>
      <header className={styles.artifactTabs}>
        <span className={styles.activeTab}>
          <ProjectIcon name="gallery" size={14} />
          Gallery
        </span>
        <button
          aria-label="Expand workspace"
          aria-pressed={controller.focusPane === "artifacts"}
          className={styles.expandTab}
          onClick={controller.toggleArtifactFocus}
          type="button"
        >
          <ProjectIcon name="expand" size={14} />
        </button>
      </header>
      <div className={styles.galleryEmptyState} role="status">
        <span aria-hidden="true" className={styles.galleryEmptyIcon}>
          <ProjectIcon name="gallery" size={22} />
        </span>
        <h2>No artifacts yet</h2>
        <p>Artifacts created in this project will appear here.</p>
      </div>
    </section>
  );
}
