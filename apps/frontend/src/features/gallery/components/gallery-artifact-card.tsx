"use client";

import Image from "next/image";
import { useState } from "react";
import { ProjectIcon, type ProjectIconName } from "@/features/projects/components/project-icon";
import { documentKindLabel } from "@/features/projects/model/project-documents";
import type { GalleryArtifact } from "../model/project-gallery";
import styles from "./project-gallery.module.css";

/**
 * A thumbnail that removes itself when the load fails, so a broken thumbnail
 * (a 502 from the thumbnail route, a version pruned behind our back) leaves the
 * same empty preview frame an absent one does — never a browser broken-image
 * element. Key this by `src` at the call site so a newer version's URL gets a
 * fresh attempt instead of inheriting the previous URL's failure.
 */
function ArtifactPreviewImage({
  loading,
  sizes,
  src,
}: {
  loading: "eager" | "lazy";
  sizes: string;
  src: string;
}) {
  const [failed, setFailed] = useState(false);
  if (failed) return null;
  return (
    /* unoptimized: the thumbnail route is session-authenticated behind
       the BFF — the Next image optimizer's server-side refetch carries
       no session cookie and would 401. The API already serves a
       card-sized PNG, so there is nothing left to optimize. */
    <Image
      alt=""
      fill
      loading={loading}
      onError={() => setFailed(true)}
      sizes={sizes}
      src={src}
      unoptimized
    />
  );
}

function typeIcon(artifact: GalleryArtifact): ProjectIconName {
  if (artifact.document) return "file-text";
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
    artifact.size?.label,
    artifact.editedLabel,
  ]
    .filter(Boolean)
    .join(", ");
  return (
    <button
      aria-label={`Open ${accessibleDetails}`}
      className={styles.artifactCard}
      data-size={artifact.size?.category}
      data-document={artifact.document ? true : undefined}
      onClick={() => onOpen(artifact)}
      title={accessibleDetails}
      type="button"
    >
      <span className={styles.artifactPreview}>
        {/* An artifact without a thumbnail (ruling 2, now the fallback rather
            than the norm — a real design document has one) renders its preview
            frame empty rather than showing placeholder artwork; a thumbnail
            that fails to load falls back to that same empty frame. */}
        {artifact.document ? (
          <span className={styles.documentPreview}><ProjectIcon name="file-text" size={28} /><span>{artifact.document.kind === "project-plan" ? "Plan" : artifact.document.kind === "icp-definition" ? "Ideal customer profile" : "Personas"}</span></span>
        ) : artifact.imagePath ? (
          <ArtifactPreviewImage
            key={artifact.imagePath}
            loading={preload ? "eager" : "lazy"}
            sizes="(max-width: 780px) 50vw, 200px"
            src={artifact.imagePath}
          />
        ) : null}
      </span>
      <span className={styles.artifactMeta}>
        <span className={styles.artifactType} data-type={artifact.collateralType ?? undefined}>
          <ProjectIcon name={typeIcon(artifact)} size={14} />
        </span>
        <span className={styles.artifactCopy}>
          <strong>{artifact.title}</strong>
          <small>{artifact.editedLabel}</small>
        </span>
        {artifact.account?.logoPath ? (
          <span className={styles.accountBadge} title={artifact.account.name}>
            <Image alt="" height={15} src={artifact.account.logoPath} unoptimized width={15} />
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
          {artifact.document ? (
          <span className={styles.documentPreview}><ProjectIcon name="file-text" size={28} /><span>{artifact.document.kind === "project-plan" ? "Plan" : artifact.document.kind === "icp-definition" ? "Ideal customer profile" : "Personas"}</span></span>
        ) : artifact.imagePath ? (
            <ArtifactPreviewImage
              key={artifact.imagePath}
              loading={preload ? "eager" : "lazy"}
              sizes="44px"
              src={artifact.imagePath}
            />
          ) : null}
        </span>
        <span>
          <strong>{artifact.title}</strong>
          <small>{artifact.document ? documentKindLabel(artifact.document.kind) : artifact.originThreadId}</small>
        </span>
      </span>
      <span className={styles.listAccountCell}>
        {artifact.account?.logoPath ? (
          <Image alt="" height={16} src={artifact.account.logoPath} unoptimized width={16} />
        ) : null}
        {artifact.account?.name}
      </span>
      <span>{artifact.collateralTypeLabel}</span>
      <span>{artifact.size?.label ?? ""}</span>
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
