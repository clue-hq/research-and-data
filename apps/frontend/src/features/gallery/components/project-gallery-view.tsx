import Image from "next/image";
import { ProjectIcon } from "@/features/projects/components/project-icon";
import type { ProjectGalleryController } from "../hooks/use-project-gallery-controller";
import type { GalleryArtifact } from "../model/project-gallery";
import {
  GalleryArtifactCard,
  GalleryArtifactListRow,
  GalleryArtifactSkeleton,
} from "./gallery-artifact-card";
import { GalleryToolbar } from "./gallery-toolbar";
import styles from "./project-gallery.module.css";

export function ProjectGalleryView({
  controller,
  documentsLoading,
  documentsError,
  onRetryDocuments,
  onOpenArtifact,
  projectTitle,
  showSkeletons,
}: {
  controller: ProjectGalleryController;
  documentsLoading?: boolean;
  documentsError?: string | null;
  onRetryDocuments?: () => void;
  onOpenArtifact: (artifact: GalleryArtifact) => void;
  projectTitle?: string;
  showSkeletons: boolean;
}) {
  const isEmpty = controller.visibleArtifactCount === 0 && !showSkeletons;
  const visibleArtifacts = controller.groups.flatMap((group) => group.artifacts);
  const eagerArtifactIds = new Set(visibleArtifacts.slice(0, 4).map((artifact) => artifact.id));
  return (
    <section aria-label="Project gallery" className={styles.gallerySurface}>
      <nav aria-label="Gallery breadcrumb" className={styles.breadcrumbBar}>
        <span>{projectTitle ?? "Project"}</span>
        <ProjectIcon name="chevron-right" size={10} />
        <strong>Gallery</strong>
        <small>{controller.visibleArtifactCount} artifacts</small>
      </nav>
      <div><GalleryToolbar controller={controller} />
      {documentsError ? <div role="alert" className={styles.documentNotice}>{documentsError} <button type="button" onClick={onRetryDocuments}>Try again</button></div> : null}</div>
      {documentsLoading && isEmpty ? <div className={styles.emptyState} role="status">Loading documents…</div> : isEmpty && !documentsError ? (
        <div className={styles.emptyState}>
          <strong>No artifacts found</strong>
          <span>Adjust the filters or create a new artifact in this project.</span>
        </div>
      ) : controller.layout === "list" ? (
        <div className={styles.listView}>
          <div aria-hidden="true" className={styles.listHeader}>
            <span>Name</span>
            <span>Account</span>
            <span>Type</span>
            <span>Size</span>
            <span>Last edited</span>
          </div>
          {visibleArtifacts.map((artifact) => (
            <GalleryArtifactListRow
              artifact={artifact}
              key={artifact.id}
              onOpen={onOpenArtifact}
              preload={eagerArtifactIds.has(artifact.id)}
            />
          ))}
        </div>
      ) : (
        <div className={styles.groupedGrid} data-grouped={controller.groupBy !== "none"}>
          {controller.groups.map((group) => (
            <section className={styles.galleryGroup} key={group.id}>
              {controller.groupBy !== "none" ? (
                <header className={styles.groupHeader}>
                  {group.account?.logoPath ? (
                    <Image alt="" height={16} src={group.account.logoPath} unoptimized width={16} />
                  ) : null}
                  <span>{group.label}</span>
                  <small>{group.artifacts.length}</small>
                </header>
              ) : null}
              <div className={styles.artifactGrid}>
                {group.artifacts.map((artifact) => (
                  <GalleryArtifactCard
                    artifact={artifact}
                    key={artifact.id}
                    onOpen={onOpenArtifact}
                    preload={eagerArtifactIds.has(artifact.id)}
                  />
                ))}
                {showSkeletons && group.id === controller.groups[0]?.id ? (
                  <>
                    <GalleryArtifactSkeleton />
                    <GalleryArtifactSkeleton />
                    <GalleryArtifactSkeleton />
                  </>
                ) : null}
              </div>
            </section>
          ))}
          {controller.groups.length === 0 && showSkeletons ? (
            <section className={styles.galleryGroup}>
              <div className={styles.artifactGrid}>
                <GalleryArtifactSkeleton />
                <GalleryArtifactSkeleton />
                <GalleryArtifactSkeleton />
              </div>
            </section>
          ) : null}
        </div>
      )}
    </section>
  );
}
