import Image from "next/image";
import { ProjectIcon, type ProjectIconName } from "@/features/projects/components/project-icon";
import type { GalleryArtifact } from "../model/project-gallery";
import styles from "./project-gallery.module.css";

function typeIcon(artifact: GalleryArtifact): ProjectIconName {
  if (artifact.collateralType === "microsite") return "web";
  if (artifact.collateralType === "account-list") return "target-accounts";
  if (artifact.collateralType === "report" || artifact.collateralType === "presentation") {
    return "file-text";
  }
  return "image";
}

export function GalleryArtifactCard({
  artifact,
  onOpen,
  preload = false,
}: {
  artifact: GalleryArtifact;
  onOpen: (artifact: GalleryArtifact) => void;
  preload?: boolean;
}) {
  const accessibleDetails = [
    artifact.title,
    artifact.account?.name,
    artifact.collateralTypeLabel,
    artifact.size.label,
    artifact.editedLabel,
  ]
    .filter(Boolean)
    .join(", ");
  return (
    <button
      aria-label={`Open ${accessibleDetails}`}
      className={styles.artifactCard}
      data-size={artifact.size.category}
      onClick={() => onOpen(artifact)}
      title={accessibleDetails}
      type="button"
    >
      <span className={styles.artifactPreview}>
        {/* A real design document has no thumbnail (ruling 2): the preview
            frame renders empty rather than showing placeholder artwork. */}
        {artifact.imagePath ? (
          <Image
            alt=""
            fill
            loading={preload ? "eager" : "lazy"}
            sizes="(max-width: 780px) 50vw, 200px"
            src={artifact.imagePath}
          />
        ) : null}
      </span>
      <span className={styles.artifactMeta}>
        <span className={styles.artifactType} data-type={artifact.collateralType}>
          <ProjectIcon name={typeIcon(artifact)} size={14} />
        </span>
        <span className={styles.artifactCopy}>
          <strong>{artifact.title}</strong>
          <small>{artifact.editedLabel}</small>
        </span>
        {artifact.account?.logoPath ? (
          <span className={styles.accountBadge} title={artifact.account.name}>
            <Image alt="" height={15} src={artifact.account.logoPath} width={15} />
          </span>
        ) : null}
      </span>
    </button>
  );
}

export function GalleryArtifactListRow({
  artifact,
  onOpen,
  preload = false,
}: {
  artifact: GalleryArtifact;
  onOpen: (artifact: GalleryArtifact) => void;
  preload?: boolean;
}) {
  return (
    <button className={styles.listRow} onClick={() => onOpen(artifact)} type="button">
      <span className={styles.listNameCell}>
        <span className={styles.listThumbnail}>
          {artifact.imagePath ? (
            <Image
              alt=""
              fill
              loading={preload ? "eager" : "lazy"}
              sizes="44px"
              src={artifact.imagePath}
            />
          ) : null}
        </span>
        <span>
          <strong>{artifact.title}</strong>
          <small>{artifact.originThreadId}</small>
        </span>
      </span>
      <span className={styles.listAccountCell}>
        {artifact.account?.logoPath ? (
          <Image alt="" height={16} src={artifact.account.logoPath} width={16} />
        ) : null}
        {artifact.account?.name}
      </span>
      <span>{artifact.collateralTypeLabel}</span>
      <span>{artifact.size.label}</span>
      <span className={styles.listEditedCell}>{artifact.editedLabel}</span>
    </button>
  );
}

export function GalleryArtifactSkeleton() {
  return (
    <div aria-label="Generating artifact" className={styles.artifactSkeleton}>
      <span />
      <i />
      <i />
    </div>
  );
}
