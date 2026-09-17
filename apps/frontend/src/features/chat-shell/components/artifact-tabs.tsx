"use client";

import type { useProjectDocumentTabs } from "@/features/projects/hooks/use-project-document-tabs";
import { useEffect, useRef } from "react";
import type { KeyboardEvent } from "react";
import type { ChatShellOpenArtifact, ChatShellSurface } from "../model/chat-shell";
import { useArtifactTabController } from "../hooks/use-artifact-tab-controller";
import { ChatShellIcon } from "./chat-shell-icon";
import { ProjectIcon } from "@/features/projects/components/project-icon";
import styles from "./chat-shell.module.css";

function ArtifactTab({
  active,
  artifact,
  onActivate,
  onClose,
  onRename,
}: {
  active: boolean;
  artifact: ChatShellOpenArtifact;
  onActivate: (artifactId: string) => void;
  onClose: (artifactId: string) => void;
  onRename: (artifactId: string, title: string) => void;
}) {
  const { id, kind, title } = artifact;
  const tabRef = useRef<HTMLDivElement>(null);
  const {
    cancelRename,
    commitRename,
    draftTitle,
    inputRef,
    renaming,
    setDraftTitle,
    startRename,
  } = useArtifactTabController({ onRename: (nextTitle) => onRename(id, nextTitle), title });

  useEffect(() => {
    if (!active) return;
    tabRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "nearest" });
  }, [active]);

  const handleRenameKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") commitRename();
    if (event.key === "Escape") cancelRename();
  };

  const handleTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== "F2") return;
    event.preventDefault();
    startRename();
  };

  return (
    <div
      className={`${styles.artifactTabUnit} ${active ? styles.artifactTabUnitActive : ""}`}
      data-artifact-tab-id={id}
      ref={tabRef}
      role="presentation"
    >
      {renaming ? (
        <div className={styles.artifactTabMain}>
          <ChatShellIcon name={kind === "web" ? "web-output" : "ad-canvas"} size={12} />
          <input
            aria-label={`Rename ${kind === "web" ? "web" : "image"} output`}
            className={styles.artifactTabRenameInput}
            onBlur={commitRename}
            onChange={(event) => setDraftTitle(event.target.value)}
            onClick={(event) => event.stopPropagation()}
            onKeyDown={handleRenameKeyDown}
            ref={inputRef}
            value={draftTitle}
          />
        </div>
      ) : (
        <button
          aria-label={`Open ${title}`}
          aria-selected={active}
          className={styles.artifactTabMain}
          onClick={() => onActivate(id)}
          onDoubleClick={startRename}
          onKeyDown={handleTabKeyDown}
          role="tab"
          tabIndex={active ? 0 : -1}
          title={`${title} — double-click to rename`}
          type="button"
        >
          <ChatShellIcon name={kind === "web" ? "web-output" : "ad-canvas"} size={12} />
          <span>{title}</span>
        </button>
      )}
      <button
        aria-label={`Close ${title}`}
        className={styles.artifactTabClose}
        onClick={() => onClose(id)}
        type="button"
      >
        <ChatShellIcon name="x" size={12} />
      </button>
    </div>
  );
}

export function ArtifactTabs({
  activeArtifactId,
  artifactMaximized,
  artifacts,
  galleryTabVisible = false,
  onActivateArtifact,
  onCloseArtifact,
  onOpenGallery,
  onOpenTargetAccounts,
  documentTabs,
  onRenameArtifact,
  onToggleMaximized,
  onTogglePanel,
  surface,
  targetAccountsBusy,
}: {
  activeArtifactId: string | null;
  artifactMaximized: boolean;
  artifacts: ChatShellOpenArtifact[];
  galleryTabVisible?: boolean;
  onActivateArtifact: (artifactId: string) => void;
  onCloseArtifact: (artifactId: string) => void;
  onOpenGallery?: () => void;
  onOpenTargetAccounts?: () => void;
  documentTabs?: ReturnType<typeof useProjectDocumentTabs>;
  onRenameArtifact: (artifactId: string, title: string) => void;
  onToggleMaximized: () => void;
  onTogglePanel: () => void;
  surface: ChatShellSurface;
  /** True while the project's discovery run is live: the Target accounts label spins. */
  targetAccountsBusy?: boolean;
}) {
  const tabListRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    tabListRef.current?.querySelector('[role="tab"][aria-selected="true"]')?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [surface, documentTabs?.selectedPath]);

  const handleTabListKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;

    const tabs = Array.from(
      event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]'),
    );
    const currentIndex = tabs.indexOf(document.activeElement as HTMLButtonElement);
    if (currentIndex < 0 || tabs.length === 0) return;

    event.preventDefault();
    const nextIndex = event.key === "Home"
      ? 0
      : event.key === "End"
        ? tabs.length - 1
        : event.key === "ArrowRight"
          ? (currentIndex + 1) % tabs.length
          : (currentIndex - 1 + tabs.length) % tabs.length;
    tabs[nextIndex]?.focus();
    tabs[nextIndex]?.click();
  };

  return (
    <div className={styles.artifactTabs}>
      <div
        aria-label="Artifact tabs"
        className={styles.artifactTabList}
        onKeyDown={handleTabListKeyDown}
        ref={tabListRef}
        role="tablist"
      >
        {galleryTabVisible ? (
          <div className={styles.galleryTabSegment}>
            <button
              aria-selected={surface === "gallery"}
              className={`${styles.galleryTab} ${surface === "gallery" ? styles.galleryTabActive : ""}`}
              onClick={onOpenGallery}
              role="tab"
              tabIndex={surface === "gallery" ? 0 : -1}
              type="button"
            >
              <ChatShellIcon name="layout-grid" size={12} />
              <span>Gallery</span>
            </button>
            {onOpenTargetAccounts ? (
              <button
                aria-selected={surface === "target-accounts"}
                className={`${styles.galleryTab} ${surface === "target-accounts" ? styles.galleryTabActive : ""}`}
                onClick={onOpenTargetAccounts}
                role="tab"
                tabIndex={surface === "target-accounts" ? 0 : -1}
                type="button"
              >
                <ProjectIcon name="target-accounts" size={12} />
                <span>Target accounts</span>
                {targetAccountsBusy ? (
                  <ProjectIcon className={styles.galleryTabSpinner} name="loader" size={12} />
                ) : null}
              </button>
            ) : null}

          </div>
        ) : null}
        <div className={styles.artifactTabScroller}>
          {documentTabs?.paths.map((path) => {
            const document = documentTabs.list.documents.find((item) => item.path === path);
            if (!document) return null;
            const active = surface === "plan" && documentTabs.selectedPath === path;
            return <div key={path} role="presentation" className={`${styles.artifactTabUnit} ${active ? styles.artifactTabUnitActive : ""}`}>
              <button role="tab" type="button" aria-selected={active} tabIndex={active ? 0 : -1} className={styles.artifactTabMain} title={document.title} onClick={() => documentTabs.openPath(path)}><ProjectIcon name="file-text" size={12} /><span>{document.title}</span></button>
              <button type="button" className={styles.artifactTabClose} aria-label={`Close ${document.title}`} onClick={() => documentTabs.close(path)}><ChatShellIcon name="x" size={12} /></button>
            </div>;
          })}
          {artifacts.map((artifact) => (
            <ArtifactTab
              active={surface === "artifact" && activeArtifactId === artifact.id}
              artifact={artifact}
              key={artifact.id}
              onActivate={onActivateArtifact}
              onClose={onCloseArtifact}
              onRename={onRenameArtifact}
            />
          ))}
        </div>
      </div>
      <div className={styles.artifactTabActions}>
        <button
          aria-label={artifactMaximized ? "Restore chat and artifact split" : "Maximize artifact"}
          aria-pressed={artifactMaximized}
          className={`${styles.iconButton} ${artifactMaximized ? styles.iconButtonPressed : ""}`}
          onClick={onToggleMaximized}
          type="button"
        >
          <ChatShellIcon name="maximize" size={14} />
        </button>
        <button
          aria-label="Close artifact panel"
          className={`${styles.iconButton} ${styles.iconButtonPressed}`}
          onClick={onTogglePanel}
          type="button"
        >
          <ChatShellIcon name="canvas-panel-close" size={12} />
        </button>
      </div>
    </div>
  );
}
