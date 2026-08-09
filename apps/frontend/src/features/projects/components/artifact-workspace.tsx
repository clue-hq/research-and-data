import type { ProjectWorkspace } from "../model/project-workspace";
import { ArtifactGallery } from "./artifact-gallery";
import { ArtifactViewer } from "./artifact-viewer";
import { ProjectIcon } from "./project-icon";
import { ProjectQuestionnaire } from "./project-questionnaire";
import { ProjectPlan } from "./project-plan";
import styles from "./project-flow.module.css";

export function ArtifactWorkspace({
  controller,
  workspace,
}: {
  controller: ReturnType<typeof import("../hooks/use-project-workspace-controller").useProjectWorkspaceController>;
  workspace: ProjectWorkspace;
}) {
  const questionnaireActive = controller.previewSurface === "questionnaire";
  const planActive = controller.previewSurface === "planning";
  return (
    <section className={styles.artifactWorkspace}>
      <header className={styles.artifactTabs}>
        <button
          aria-current={controller.surface === "gallery" && !questionnaireActive && !planActive ? "page" : undefined}
          className={controller.surface === "gallery" && !questionnaireActive && !planActive ? styles.activeTab : undefined}
          onClick={controller.openGallery}
          type="button"
        >
          <ProjectIcon name="gallery" size={14} />Gallery
        </button>
        {!questionnaireActive ? (
          <button onClick={controller.openTargetAccounts} type="button"><ProjectIcon name="target-accounts" size={12} />Target accounts</button>
        ) : null}
        {questionnaireActive ? (
          <button className={styles.activeTab} type="button"><ProjectIcon name="clipboard-list" size={12} />Questionnaire</button>
        ) : planActive ? (
          <button className={styles.activeTab} type="button"><ProjectIcon name="file-text" size={12} />Plan</button>
        ) : controller.surface === "artifact" ? (
          <button className={styles.activeTab} type="button">
            <ProjectIcon name={controller.selectedArtifact.type === "website" ? "globe" : controller.selectedArtifact.type === "table" ? "target-accounts" : "edit"} size={14} />
            <span>{controller.selectedArtifact.viewerTitle ?? controller.selectedArtifact.title}</span>
          </button>
        ) : null}
        <button aria-label="Expand workspace" aria-pressed={controller.focusPane === "artifacts"} className={styles.expandTab} onClick={controller.toggleArtifactFocus} type="button"><ProjectIcon name="expand" size={14} /></button>
      </header>
      {questionnaireActive ? (
        <div className={styles.questionnaireStage}>
          <ProjectQuestionnaire
            data={workspace.questionnaire}
            onChange={controller.setQuestionnaire}
            onSubmit={controller.submitQuestionnaire}
            value={controller.questionnaire}
          />
        </div>
      ) : planActive ? (
        <ProjectPlan plan={workspace.plan} />
      ) : controller.surface === "gallery" ? (
        <ArtifactGallery
          artifactFilter={controller.artifactFilter}
          artifactSort={controller.artifactSort}
          artifacts={controller.galleryArtifacts}
          galleryLayout={controller.galleryLayout}
          galleryQuery={controller.galleryQuery}
          groupByAccount={controller.groupByAccount}
          onArtifactFilterChange={controller.setArtifactFilter}
          onArtifactSortChange={controller.setArtifactSort}
          onGalleryLayoutChange={controller.setGalleryLayout}
          onGalleryQueryChange={controller.setGalleryQuery}
          onGroupByAccountChange={controller.setGroupByAccount}
          onOpenArtifact={controller.openArtifact}
        />
      ) : (
        <ArtifactViewer
          artifact={controller.selectedArtifact}
          ctaLabel={controller.ctaLabel}
          headline={controller.editableHeadline}
          headlineAlign={controller.headlineAlign}
          headlineColor={controller.headlineColor}
          headlineFont={controller.headlineFont}
          headlineSize={controller.headlineSize}
          headlineWeight={controller.headlineWeight}
          heroImageFit={controller.heroImageFit}
          heroImagePath={controller.heroImagePath}
          heroImageRadius={controller.heroImageRadius}
          inspectorOpen={controller.inspectorOpen}
          inspectorSelection={controller.inspectorSelection}
          onHeadlineAlignChange={controller.setHeadlineAlign}
          onHeadlineColorChange={controller.setHeadlineColor}
          onHeadlineFontChange={controller.setHeadlineFont}
          onHeadlineSizeChange={controller.setHeadlineSize}
          onHeadlineWeightChange={controller.setHeadlineWeight}
          onPreviewDeviceChange={controller.cyclePreviewDevice}
          onPreviewZoomChange={controller.setPreviewZoom}
          onSelect={controller.selectInspector}
          previewDevice={controller.previewDevice}
          previewZoom={controller.previewZoom}
        />
      )}
    </section>
  );
}
