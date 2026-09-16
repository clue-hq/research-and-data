"use client";

import Link from "next/link";
import { Button, buttonVariants } from "@/components/ui/button";
import { useEffect, useRef, useState } from "react";
import {
  Archive,
  ArrowUpRight,
  Bookmark,
  ChevronLeft,
  ChevronRight,
  Download,
  Link2,
  Pencil,
  RotateCcw,
  X,
} from "lucide-react";
import { normalizeGalleryArtifact } from "@/features/gallery/model/project-gallery";
import {
  projectArtifactHref,
  projectChatHref,
  projectGalleryHref,
} from "@/features/chat-shell/model/chat-shell-routes";
import { ImageExportMenu } from "@/features/chat-shell/components/image-export-menu";
import { useImageExportController } from "@/features/chat-shell/hooks/use-image-export-controller";
import { exportFilename } from "@/features/design-editor/adapter/scene-export";
import type { ArtifactActions } from "../hooks/use-artifact-actions";
import type { LibraryArtifact } from "../model/artifact-library";
import styles from "./artifact-library.module.css";

/**
 * Artifacts page (2026-09-15): the library's preview dialog. It owns no write
 * of its own — rename, save and archive are `actions`, the one place a refusal
 * is caught and announced — and it opens the editor by asking for a new chat
 * rather than deep-linking a thread the operator has not got.
 *
 * Downloads split by kind: an ad exports the *saved document* through the
 * design API (every format and scale the editor offers) and can also take its
 * original image, while a web artifact has one Export — the design API's
 * self-contained static-site zip (founder ruling 2026-09-16), the thing a
 * marketer can actually publish, rather than a picture of the page.
 */
export function ArtifactLibraryPreview({
  actions,
  artifact,
  onClose,
}: {
  actions: ArtifactActions;
  artifact: LibraryArtifact;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [page, setPage] = useState(0);
  const [renaming, setRenaming] = useState(false);
  const [title, setTitle] = useState(artifact.title);
  const [message, setMessage] = useState("");
  const paths = [
    ...new Set([artifact.imagePath, ...(artifact.canvasPagePaths ?? [])]),
  ];
  const imagePath = paths[page] ?? artifact.imagePath;
  const normalized = normalizeGalleryArtifact(artifact);
  const projectId = artifact.projectId;
  const href = projectArtifactHref(projectId, artifact.id);
  const { controller: exportController, menuRef: exportMenuRef } =
    useImageExportController({
      title: artifact.title,
      onExport: (options) => actions.exportAd(artifact, options),
    });

  useEffect(() => {
    const element = dialog.current;
    const previous = document.activeElement as HTMLElement | null;
    element?.showModal();
    return () => {
      element?.close();
      previous?.focus();
    };
  }, []);

  return (
    <dialog
      aria-label={`Preview ${artifact.title}`}
      className={styles.previewDialog}
      ref={dialog}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className={styles.previewShell}>
        <header className={styles.previewHeader}>
          <span>{normalized.collateralTypeLabel}</span>
          <strong>{artifact.title}</strong>
          <Button
            size="icon-sm"
            variant="transparent"
            aria-label="Close artifact preview"
            className={styles.iconAction}
            onClick={onClose}
          >
            <X size={18} />
          </Button>
        </header>
        <div className={styles.previewBody}>
          <section
            className={styles.previewCanvas}
            aria-label="Artifact preview"
          >
            <div className={styles.previewImage}>
              {/* The original asset, rather than an optimized thumbnail, is the downloadable preview. */}
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img alt={artifact.title} src={imagePath} />
            </div>
            {paths.length > 1 ? (
              <nav className={styles.pageControls} aria-label="Artifact pages">
                <Button
                  size="icon-sm"
                  variant="transparent"
                  aria-label="Previous page"
                  disabled={page === 0}
                  onClick={() => setPage((current) => current - 1)}
                >
                  <ChevronLeft size={15} />
                </Button>
                <span>
                  Page {page + 1} of {paths.length}
                </span>
                <Button
                  size="icon-sm"
                  variant="transparent"
                  aria-label="Next page"
                  disabled={page === paths.length - 1}
                  onClick={() => setPage((current) => current + 1)}
                >
                  <ChevronRight size={15} />
                </Button>
              </nav>
            ) : null}
          </section>
          <aside className={styles.details}>
            <div className={styles.detailsTitle}>
              <h2>Artifact details</h2>
              <Button
                size="icon-sm"
                variant="transparent"
                aria-label="Rename artifact"
                className={styles.iconAction}
                onClick={() => {
                  setTitle(artifact.title);
                  setRenaming(true);
                }}
              >
                <Pencil size={13} />
              </Button>
            </div>
            {renaming ? (
              <form
                className={styles.renameForm}
                onSubmit={async (event) => {
                  event.preventDefault();
                  if (!title.trim()) return;
                  if (await actions.rename(artifact, title.trim())) {
                    setRenaming(false);
                  }
                }}
              >
                <label>
                  Name
                  <input
                    aria-label="Artifact name"
                    autoFocus
                    maxLength={160}
                    value={title}
                    onChange={(event) => setTitle(event.target.value)}
                  />
                </label>
                <div>
                  <Button
                    size="sm"
                    variant="transparent"
                    type="button"
                    onClick={() => setRenaming(false)}
                  >
                    Cancel
                  </Button>
                  <Button
                    size="sm"
                    variant="default"
                    disabled={!title.trim() || actions.busy}
                    type="submit"
                  >
                    Save name
                  </Button>
                </div>
              </form>
            ) : (
              <p className={styles.detailName}>{artifact.title}</p>
            )}
            <dl>
              <dt>Account</dt>
              <dd>
                {artifact.account ? (
                  artifact.account.accountEntityId ? (
                    <Link href={`/accounts/${artifact.account.accountEntityId}`}>
                      {artifact.account.name}
                      <ArrowUpRight size={12} />
                    </Link>
                  ) : (
                    artifact.account.name
                  )
                ) : (
                  "No account"
                )}
              </dd>
              <dt>Type</dt>
              <dd>{normalized.collateralTypeLabel}</dd>
              <dt>Project</dt>
              <dd>
                <Link
                  href={projectGalleryHref(projectId, artifact.originThreadId)}
                >
                  {artifact.projectTitle}
                  <ArrowUpRight size={12} />
                </Link>
              </dd>
              {artifact.size ? (
                <>
                  <dt>Size</dt>
                  <dd>{artifact.size.label}</dd>
                </>
              ) : null}
              <dt>Last edited</dt>
              <dd>
                {artifact.updatedAt
                  ? new Date(artifact.updatedAt).toLocaleDateString("en-US", {
                      month: "short",
                      day: "numeric",
                      year: "numeric",
                      timeZone: "UTC",
                    })
                  : "Unavailable"}
              </dd>
            </dl>
            <div className={styles.detailActions}>
              <Button
                size="md"
                variant="secondary"
                className={styles.fullWidthButton}
                disabled={actions.busy}
                onClick={() => actions.openEditor(artifact)}
              >
                <Pencil size={14} />
                Open editor
                <ArrowUpRight size={12} />
              </Button>
              <Link
                className={buttonVariants({
                  size: "md",
                  variant: "transparent",
                  className: styles.textAction,
                })}
                href={projectChatHref(projectId, artifact.originThreadId)}
              >
                <ArrowUpRight size={14} />
                Open source conversation
              </Link>
              <Button
                size="md"
                variant="transparent"
                className={styles.textAction}
                onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(
                      new URL(href, window.location.origin).href,
                    );
                    setMessage("Artifact link copied.");
                  } catch {
                    // The clipboard is the browser's to refuse, not a write of
                    // ours: it answers on this dialog's own inline line, and
                    // `useArtifactActions` stays the only catch site for the
                    // artifact writes.
                    setMessage("Couldn’t copy the link. Please try again.");
                  }
                }}
              >
                <Link2 size={14} />
                Copy artifact link
              </Button>
            </div>
            <div className={styles.detailActions}>
              {artifact.kind === "ad" ? (
                <div className={styles.exportAnchor} ref={exportMenuRef}>
                  <Button
                    size="md"
                    variant="default"
                    aria-expanded={exportController.menuOpen}
                    className={styles.fullWidthButton}
                    onClick={exportController.toggleMenu}
                  >
                    <Download size={14} />
                    Download preview
                  </Button>
                  {exportController.menuOpen ? (
                    /* A refused export has to be SEEN, not just announced: the
                       menu promotes its status line out of the screen-reader
                       -only span only when the status says `failed`. There is
                       no window listener on this page to supply one, so the
                       controller's own direct-leg outcome becomes the status.
                       A success stays `undefined`, which leaves the menu's
                       optimistic line exactly as it renders in the editor. */
                    <ImageExportMenu
                      controller={exportController}
                      exportStatus={
                        exportController.exportFailed
                          ? { failed: true, message: exportController.statusMessage }
                          : undefined
                      }
                    />
                  ) : null}
                </div>
              ) : (
                <Button
                  size="md"
                  variant="default"
                  className={styles.fullWidthButton}
                  disabled={actions.busy}
                  onClick={() => actions.exportWeb(artifact)}
                >
                  <Download size={14} />
                  Export
                </Button>
              )}
              {artifact.kind === "ad" ? (
                <a
                  className={buttonVariants({
                    size: "md",
                    variant: "transparent",
                    className: styles.textAction,
                  })}
                  href={imagePath}
                  download={exportFilename(artifact.title, "PNG")}
                >
                  <Download size={14} />
                  Original image
                </a>
              ) : null}
              {/* The dummy's "Download table (.csv)" action is not lifted: a
                  library row is a design document (web or ad) and never carries
                  `tableContent`, so the block could not render, and the CSV
                  machinery it called does not exist in this repo. */}
            </div>
            <div className={styles.detailActions}>
              <Button
                size="md"
                variant="transparent"
                className={styles.textAction}
                aria-pressed={artifact.saved}
                disabled={actions.busy}
                onClick={() => actions.save(artifact, !artifact.saved)}
              >
                <Bookmark
                  size={14}
                  fill={artifact.saved ? "currentColor" : "none"}
                />
                {artifact.saved ? "Remove from saved" : "Save artifact"}
              </Button>
              <Button
                size="md"
                variant="transparent"
                className={styles.textAction}
                disabled={actions.busy}
                onClick={async () => {
                  if (await actions.archive(artifact, !artifact.archivedAt)) {
                    onClose();
                  }
                }}
              >
                {artifact.archivedAt ? (
                  <RotateCcw size={14} />
                ) : (
                  <Archive size={14} />
                )}
                {artifact.archivedAt ? "Restore artifact" : "Archive artifact"}
              </Button>
            </div>
            {message ? (
              <p className={styles.inlineMessage} role="status">
                {message}
              </p>
            ) : null}
          </aside>
        </div>
      </div>
    </dialog>
  );
}
