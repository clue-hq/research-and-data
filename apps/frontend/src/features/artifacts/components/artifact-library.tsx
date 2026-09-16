"use client";

import Image from "next/image";
import Link from "next/link";
import { Button, buttonVariants } from "@/components/ui/button";
import { useMemo, useState } from "react";
import {
  Archive,
  Bookmark,
  Download,
  FolderOpen,
  Images,
  Plus,
  X,
} from "lucide-react";
import { ApplicationShell } from "@/components/shell/application-shell";
import { exportFilename } from "@/features/design-editor/adapter/scene-export";
import { GalleryArtifactCard } from "@/features/gallery/components/gallery-artifact-card";
import { GalleryToolbar } from "@/features/gallery/components/gallery-toolbar";
import { useProjectGalleryController } from "@/features/gallery/hooks/use-project-gallery-controller";
import type { GalleryArtifact } from "@/features/gallery/model/project-gallery";
import { useArtifactActions } from "../hooks/use-artifact-actions";
import {
  libraryKey,
  type ArtifactLibraryData,
  type LibraryArtifact,
} from "../model/artifact-library";
import { ArtifactLibraryPreview } from "./artifact-library-preview";
import styles from "./artifact-library.module.css";

/**
 * Artifacts page (2026-09-15): the workspace-wide library. The rows arrive
 * already shaped by `toLibraryArtifact` — the thumbnail URL, the "Edited …"
 * label, the last-viewed instant and the account favicon are the model's, and
 * nothing here recomputes them.
 *
 * Collections are the backend's marks, not a browser-storage organization:
 * "Saved" reads `artifact.saved`, "Archived" reads `artifact.archivedAt`, and
 * every write goes through `useArtifactActions`, which refreshes this server
 * component so the screen shows what was actually recorded.
 */
export function ArtifactLibrary({ data }: { data: ArtifactLibraryData }) {
  const actions = useArtifactActions();
  const [collection, setCollection] = useState<"all" | "saved" | "archived">(
    "all",
  );
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const scoped = useMemo(
    () =>
      data.artifacts.filter((artifact) =>
        collection === "archived"
          ? !!artifact.archivedAt
          : !artifact.archivedAt && (collection !== "saved" || artifact.saved),
      ),
    [collection, data.artifacts],
  );
  const controller = useProjectGalleryController(scoped);
  const selected = data.artifacts.find(
    (artifact) => libraryKey(artifact) === selectedKey,
  );
  const projectCount = new Set(scoped.map((artifact) => artifact.projectId))
    .size;
  const hasSearch = Boolean(
    controller.query.trim() || controller.activeFilterCount,
  );

  function open(artifact: GalleryArtifact) {
    const source = artifact.source as LibraryArtifact;
    setSelectedKey(libraryKey(source));
    actions.viewed(source);
  }
  function clear() {
    controller.resetFilters();
    controller.setQuery("");
  }

  return (
    <ApplicationShell activeHref="/artifacts">
      <main className={styles.library}>
        <header className={styles.pageHeader}>
          <div>
            <Images size={17} strokeWidth={1.4} />
            <h1>Artifacts</h1>
          </div>
          <Link
            className={buttonVariants({ size: "md", variant: "secondary" })}
            href="/"
          >
            <Plus size={14} />
            Create in chat
          </Link>
        </header>
        <div className={styles.collectionBar}>
          <nav aria-label="Artifact collections" className={styles.collections}>
            <button
              aria-current={collection === "all" ? "page" : undefined}
              onClick={() => setCollection("all")}
            >
              All artifacts{" "}
              <span>
                {data.artifacts.filter((artifact) => !artifact.archivedAt).length}
              </span>
            </button>
            <button
              aria-current={collection === "saved" ? "page" : undefined}
              onClick={() => setCollection("saved")}
            >
              <Bookmark size={13} />
              Saved
            </button>
            <button
              aria-current={collection === "archived" ? "page" : undefined}
              onClick={() => setCollection("archived")}
            >
              <Archive size={13} />
              Archived
            </button>
          </nav>
          <span className={styles.collectionSummary}>
            {projectCount} {projectCount === 1 ? "project" : "projects"}
          </span>
        </div>
        <GalleryToolbar controller={controller} library />
        {hasSearch ? (
          <div className={styles.filterSummary}>
            <span>
              {controller.visibleArtifactCount}{" "}
              {controller.visibleArtifactCount === 1 ? "artifact" : "artifacts"}{" "}
              found
              {controller.query.trim()
                ? ` for “${controller.query.trim()}”`
                : ""}
            </span>
            <Button size="sm" variant="transparent" onClick={clear}>
              Clear filters <X size={12} />
            </Button>
          </div>
        ) : null}
        <div className={styles.content}>
          {controller.visibleArtifactCount === 0 ? (
            <div className={styles.emptyState}>
              {collection === "saved" ? (
                <Bookmark size={26} strokeWidth={1.3} />
              ) : collection === "archived" ? (
                <Archive size={26} strokeWidth={1.3} />
              ) : (
                <Images size={26} strokeWidth={1.3} />
              )}
              <h2>
                {hasSearch
                  ? "No artifacts match your search"
                  : collection === "saved"
                    ? "Keep your go-to artifacts here"
                    : collection === "archived"
                      ? "No archived artifacts"
                      : "Your artifacts will live here"}
              </h2>
              <p>
                {hasSearch
                  ? "Try another name, account, type, or project."
                  : collection === "saved"
                    ? "Save an artifact to find it quickly next time."
                    : collection === "archived"
                      ? "Artifacts you archive stay here until you restore them."
                      : "Create something in a project chat and find it here, ready to view and download."}
              </p>
              {hasSearch ? (
                <Button size="md" variant="secondary" onClick={clear}>
                  Clear filters
                </Button>
              ) : collection === "all" ? (
                <Link
                  className={buttonVariants({
                    size: "md",
                    variant: "secondary",
                  })}
                  href="/"
                >
                  Create in chat
                </Link>
              ) : (
                <Button
                  size="md"
                  variant="secondary"
                  onClick={() => setCollection("all")}
                >
                  Browse all artifacts
                </Button>
              )}
            </div>
          ) : (
            controller.groups.map((group) => (
              <section
                className={styles.group}
                key={group.id}
                aria-label={group.label}
              >
                {controller.groupBy !== "none" ? (
                  <h2 className={styles.groupHeading}>
                    {group.account?.logoPath ? (
                      <Image
                        src={group.account.logoPath}
                        alt=""
                        width={16}
                        height={16}
                      />
                    ) : controller.groupBy === "project" ? (
                      <FolderOpen size={15} />
                    ) : null}
                    {group.label}
                    <span>{group.artifacts.length}</span>
                  </h2>
                ) : null}
                {controller.layout === "grid" ? (
                  <div className={styles.grid}>
                    {group.artifacts.map((artifact, index) => {
                      const source = artifact.source as LibraryArtifact;
                      return (
                        <article
                          className={styles.card}
                          key={libraryKey(source)}
                        >
                          <GalleryArtifactCard
                            artifact={artifact}
                            onOpen={open}
                            preload={index < 4}
                          />
                          <div className={styles.cardFooter}>
                            <span title={artifact.project?.title}>
                              <FolderOpen size={12} />
                              {artifact.project?.title ?? "No project"}
                            </span>
                            <div>
                              <Button
                                size="icon-sm"
                                variant="transparent"
                                aria-label={
                                  source.saved
                                    ? `Unsave ${artifact.title}`
                                    : `Save ${artifact.title}`
                                }
                                aria-pressed={source.saved}
                                onClick={() => actions.save(source, !source.saved)}
                                title="Save artifact"
                              >
                                <Bookmark
                                  size={14}
                                  fill={source.saved ? "currentColor" : "none"}
                                />
                              </Button>
                              <a
                                className={buttonVariants({
                                  size: "icon-sm",
                                  variant: "transparent",
                                })}
                                aria-label={`Download ${artifact.title} preview`}
                                download={exportFilename(artifact.title, "PNG")}
                                href={artifact.imagePath!}
                                title="Download original preview"
                              >
                                <Download size={14} />
                              </a>
                            </div>
                          </div>
                        </article>
                      );
                    })}
                  </div>
                ) : (
                  <div className={styles.tableScroll}>
                    <table className={styles.table}>
                      <thead>
                        <tr>
                          <th>Name</th>
                          <th>Account</th>
                          <th>Type</th>
                          <th>Project</th>
                          <th>Last edited</th>
                          <th>
                            <span className="sr-only">Actions</span>
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {group.artifacts.map((artifact) => (
                          <tr key={libraryKey(artifact.source as LibraryArtifact)}>
                            <td>
                              <button
                                className={styles.tableName}
                                onClick={() => open(artifact)}
                              >
                                {/* unoptimized for the same reason the gallery
                                    card gives: the thumbnail route is session
                                    -authenticated behind the BFF, and the Next
                                    optimizer's server-side refetch carries no
                                    session cookie. */}
                                <Image
                                  src={artifact.imagePath!}
                                  alt=""
                                  width={42}
                                  height={34}
                                  style={{ width: 42, height: 34 }}
                                  unoptimized
                                />
                                <span>{artifact.title}</span>
                              </button>
                            </td>
                            <td>
                              <span className={styles.tableAccount}>
                                {artifact.account?.logoPath ? (
                                  <Image
                                    src={artifact.account.logoPath}
                                    alt=""
                                    width={16}
                                    height={16}
                                  />
                                ) : null}
                                {artifact.account?.name}
                              </span>
                            </td>
                            <td>{artifact.collateralTypeLabel}</td>
                            <td>{artifact.project?.title ?? "No project"}</td>
                            <td>
                              {artifact.editedLabel.replace("Edited ", "")}
                            </td>
                            <td>
                              <Button
                                size="icon-sm"
                                variant="transparent"
                                aria-label={`View ${artifact.title} details`}
                                onClick={() => open(artifact)}
                              >
                                <FolderOpen size={14} />
                              </Button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            ))
          )}
        </div>
        {actions.notice ? (
          <div className={styles.toast} role="status">
            {actions.notice}
            <Button
              size="icon-sm"
              variant="transparent"
              aria-label="Dismiss notification"
              onClick={actions.dismissNotice}
            >
              <X size={14} />
            </Button>
          </div>
        ) : null}
        {selected ? (
          <ArtifactLibraryPreview
            actions={actions}
            artifact={selected}
            key={selectedKey}
            onClose={() => setSelectedKey(null)}
          />
        ) : null}
      </main>
    </ApplicationShell>
  );
}
