import Image from "next/image";
import type {
  ArtifactFilter,
  ArtifactSort,
  GalleryLayout,
  ProjectArtifact,
} from "../model/project-workspace";
import { ProjectIcon } from "./project-icon";
import styles from "./project-flow.module.css";

function ArtifactCard({
  artifact,
  onOpen,
}: {
  artifact: ProjectArtifact;
  onOpen: (artifactId: string) => void;
}) {
  return (
    <button className={styles.artifactCard} onClick={() => onOpen(artifact.id)} type="button">
      <span className={styles.artifactPreview}>
        {/* unoptimized for the same reason the gallery card documents in full:
            the thumbnail route is session-authenticated behind the BFF and the
            Next image optimizer's server-side refetch would 401. */}
        {artifact.imagePath ? (
          <Image alt="" fill loading="eager" sizes="360px" src={artifact.imagePath} unoptimized />
        ) : null}
      </span>
      <span className={styles.artifactCardMeta}>
        <span className={styles.artifactType} data-type={artifact.type}>
          <ProjectIcon
            name={artifact.type === "table" ? "target-accounts" : artifact.type === "website" ? "web" : "image"}
            size={16}
          />
        </span>
        <span>
          <strong>{artifact.title}</strong>
          <small>{artifact.editedLabel}</small>
        </span>
        {artifact.accountLogoPath ? (
          <span className={styles.accountBadge}>
            <Image alt="" height={16} src={artifact.accountLogoPath} unoptimized width={16} />
          </span>
        ) : null}
      </span>
    </button>
  );
}

function ArtifactSkeleton() {
  return (
    <div aria-label="Generating artifact" className={styles.artifactSkeleton}>
      <span /><i /><i />
    </div>
  );
}

export function ArtifactGallery({
  artifacts,
  artifactFilter,
  artifactSort,
  galleryLayout,
  galleryQuery,
  groupByAccount,
  onArtifactFilterChange,
  onArtifactSortChange,
  onGalleryLayoutChange,
  onGalleryQueryChange,
  onGroupByAccountChange,
  onOpenArtifact,
  showSkeletons = false,
}: {
  artifacts: ProjectArtifact[];
  artifactFilter: ArtifactFilter;
  artifactSort: ArtifactSort;
  galleryLayout: GalleryLayout;
  galleryQuery: string;
  groupByAccount: boolean;
  onArtifactFilterChange: (filter: ArtifactFilter) => void;
  onArtifactSortChange: (sort: ArtifactSort) => void;
  onGalleryLayoutChange: (layout: GalleryLayout) => void;
  onGalleryQueryChange: (query: string) => void;
  onGroupByAccountChange: (grouped: boolean) => void;
  onOpenArtifact: (artifactId: string) => void;
  /** Placeholder tiles while a generation run is producing. */
  showSkeletons?: boolean;
}) {
  return (
    <section className={styles.gallerySurface}>
      <header className={styles.galleryToolbar}>
        <label>
          <ProjectIcon name="search" size={14} />
          <input
            aria-label="Search artifacts"
            onChange={(event) => onGalleryQueryChange(event.target.value)}
            placeholder="Search"
            type="search"
            value={galleryQuery}
          />
        </label>
        <div>
          <label className={styles.toolbarSelect}>
            <select aria-label="Sort artifacts" onChange={(event) => onArtifactSortChange(event.target.value as ArtifactSort)} value={artifactSort}>
              <option value="last-viewed">Last viewed</option>
              <option value="name">Name</option>
            </select>
            <ProjectIcon name="chevron-down" size={12} />
          </label>
          <label className={styles.toolbarSelect}>
            <select aria-label="Group artifacts" onChange={(event) => onGroupByAccountChange(event.target.value === "account")} value={groupByAccount ? "account" : "none"}>
              <option value="none">Group by</option>
              <option value="account">Account</option>
            </select>
            <ProjectIcon name="chevron-down" size={12} />
          </label>
          <label className={styles.toolbarSelect}>
            <select aria-label="Filter artifacts" onChange={(event) => onArtifactFilterChange(event.target.value as ArtifactFilter)} value={artifactFilter}>
              <option value="all">Filter</option>
              <option value="table">Tables</option>
              <option value="website">Websites</option>
              <option value="canvas">Canvas</option>
              <option value="presentation">Presentations</option>
            </select>
            <ProjectIcon name="chevron-down" size={12} />
          </label>
          <span className={styles.layoutToggle}>
            <button
              aria-label="Grid view"
              aria-pressed={galleryLayout === "grid"}
              onClick={() => onGalleryLayoutChange("grid")}
              type="button"
            ><ProjectIcon name="grid" size={14} /></button>
            <button
              aria-label="List view"
              aria-pressed={galleryLayout === "list"}
              onClick={() => onGalleryLayoutChange("list")}
              type="button"
            ><ProjectIcon name="list" size={14} /></button>
          </span>
        </div>
      </header>
      {artifacts.length === 0 && !showSkeletons ? (
        <p className={styles.galleryEmpty}>Artifacts you create will appear here</p>
      ) : (
        <div
          className={galleryLayout === "grid" ? styles.artifactGrid : styles.artifactList}
          data-grouped={groupByAccount}
        >
          {artifacts.map((artifact) => (
            <ArtifactCard artifact={artifact} key={artifact.id} onOpen={onOpenArtifact} />
          ))}
          {showSkeletons ? <><ArtifactSkeleton /><ArtifactSkeleton /><ArtifactSkeleton /></> : null}
        </div>
      )}
    </section>
  );
}
