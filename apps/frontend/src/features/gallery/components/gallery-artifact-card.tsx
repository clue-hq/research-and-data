"use client";

import Image from "next/image";
import { useState } from "react";
import { ProjectIcon, type ProjectIconName } from "@/features/projects/components/project-icon";
import { documentKindLabel } from "@/features/projects/model/project-documents";
import { useDesignThumbnail } from "../hooks/use-design-thumbnail";
import type { GalleryArtifact } from "../model/project-gallery";
import styles from "./project-gallery.module.css";

/**
 * A thumbnail that may still be rendering in the background (2026-10-29): it shows an older
 * version's card while this version renders, nothing while a brand-new one renders, and asks
 * again until it has this version's (`useDesignThumbnail`). A failed load leaves the same empty
 * preview frame an absent thumbnail does — never a browser broken-image element. Key this by
 * `src` at the call site so a newer version's URL starts over.
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
  const thumbnail = useDesignThumbnail(src);
  const [failed, setFailed] = useState(false);
  if (failed || thumbnail.failed || !thumbnail.src) return null;
  return (
    /* unoptimized: the image is already a card-sized PNG, held as an object URL. */
    <Image
      alt=""
      fill
      loading={loading}
      onError={() => setFailed(true)}
      sizes={sizes}
      src={thumbnail.src}
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
