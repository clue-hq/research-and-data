"use client";

import {
  CheckIcon,
  ChevronDownIcon,
  DownloadIcon,
  EllipsisIcon,
  MonitorIcon,
  RectangleHorizontalIcon,
  RectangleVerticalIcon,
  type LucideIcon,
} from "lucide-react";
import type { KeyboardEvent } from "react";
import type { SceneExportStatus } from "@/features/design-editor/adapter/scene-export";
import type { ChatShellArtifactKind } from "../model/chat-shell";
import type {
  ImageExportFormat,
  ImageExportPreview,
  ImageExportScale,
} from "../model/image-export";
import { useArtifactActionMenuController } from "../hooks/use-artifact-action-menu-controller";
import { useArtifactSharingController } from "../hooks/use-artifact-sharing-controller";
import { useArtifactTabController } from "../hooks/use-artifact-tab-controller";
import { useArtifactToolbarController } from "../hooks/use-artifact-toolbar-controller";
import { useImageExportController } from "../hooks/use-image-export-controller";
import { ArtifactActionMenu } from "./artifact-action-menu";
import { ArtifactShareMenu } from "./artifact-share-menu";
import { ChatShellIcon } from "./chat-shell-icon";
import { ImageExportMenu } from "./image-export-menu";
import styles from "./chat-shell.module.css";

const PREVIEW_DEVICES = ["Desktop", "Tablet", "Mobile"] as const;
const PREVIEW_DEVICE_ICONS = {
  Desktop: MonitorIcon,
  Mobile: RectangleVerticalIcon,
  Tablet: RectangleHorizontalIcon,
} satisfies Record<(typeof PREVIEW_DEVICES)[number], LucideIcon>;
// §2 delta (contract row 5 / §1.10): zoom offers 10%–150% in 5% steps, in a
// scrollable menu (`.toolbarMenuScrollable`) — every one of them inside the
// engine's own [0.1, 2.0] viewport clamp. AD2.8 binds the menu to the real
// viewport: fit-on-open supplies the value shown before any choice, and a
// choice moves the canvas to exactly that percentage.
const ZOOM_LEVELS = Array.from({ length: 29 }, (_, index) => `${10 + index * 5}%`);

export function ArtifactHeader({
  documentId,
  editing,
  exportPreview,
  exportStatus,
  kind,
  onEdit,
  onRename,
  onRequestExportPreview,
  onZoomChange,
  redoDisabled,
  title,
  undoDisabled,
  zoom,
}: {
  /** The active web document, so the share menu reads and writes its real
   * publish state. */
  documentId?: string | null;
  editing: boolean;
  /** AD4.D step 3: the ad session's render for the export menu's designed
   * preview region, with the element that hosts it. Absent on every other
   * path. */
  exportPreview?: ImageExportPreview | null;
  /** AD4.D step 2: the ad session's export outcome, for the export menu's
   * status line. Absent on every other path. */
  exportStatus?: SceneExportStatus | null;
  kind: ChatShellArtifactKind;
  onEdit: () => void;
  onRename: (title: string) => void;
  /** AD4.D step 3: the export menu's request for a preview at the settings it
   * is currently showing. Absent on every other path. */
  onRequestExportPreview?: (
    format: ImageExportFormat,
    scale: ImageExportScale,
  ) => void;
  /** AD2.8: a zoom the user picked from the menu, reported to the ad editing
   * session — which owns the value and hands it back through `zoom`. The WEB
   * branch below renders the device menu instead and never touches either. */
  onZoomChange?: (zoom: string) => void;
  /** W3.4: empty-stack disable for the action menu's Redo. */
  redoDisabled?: boolean;
  title: string;
  /** W3.4: empty-stack disable for the action menu's Undo. */
  undoDisabled?: boolean;
  /** AD2.8: the zoom to DISPLAY — the session's choice, or (until there is
   * one) the canvas's fit-on-open snapped to the nearest step this menu
   * offers. Absent leaves the toolbar controller's own local value. */
  zoom?: string | null;
}) {
  const {
    closeMenu: closeArtifactActionMenu,
    menuOpen: artifactActionMenuOpen,
    menuRef: artifactActionMenuRef,
    requestAction: requestArtifactAction,
    selectVersion,
    selectedVersionId,
    setVersionsOpen,
    toggleMenu: toggleArtifactActionMenu,
    versionsOpen,
  } = useArtifactActionMenuController(kind);
  const {
    cancelRename,
    commitRename,
    draftTitle,
    inputRef: renameInputRef,
    renaming,
    setDraftTitle,
    startRename,
  } = useArtifactTabController({ onRename, title });
  const {
    controller: sharingController,
    menuRef: sharingMenuRef,
  } = useArtifactSharingController({ kind, title, documentId });
  const {
    controller: imageExportController,
    menuRef: imageExportMenuRef,
  } = useImageExportController({ title });
  const {
    chooseDevice,
    chooseZoom,
    closeMenus: closeToolbarMenus,
    device,
    deviceMenuOpen,
    deviceMenuRef,
    toggleDeviceMenu,
    toggleZoomMenu,
    zoom: activeZoom,
    zoomMenuOpen,
    zoomMenuRef,
    // AD2.8: zoom is now LIFTED — the session owns it, because the same value
    // has to drive the canvas viewport. The device menu (the web branch) is
    // untouched and still lives entirely inside this controller.
  } = useArtifactToolbarController({ onZoomChange, zoom });
  const handleRenameKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") commitRename();
    if (event.key === "Escape") cancelRename();
  };

  const beginRename = () => {
    closeArtifactActionMenu();
    startRename();
  };

  const toggleActions = () => {
    closeToolbarMenus();
    sharingController.closeMenu();
    imageExportController.closeMenu();
    toggleArtifactActionMenu();
  };
  const PreviewDeviceIcon = PREVIEW_DEVICE_ICONS[device];

  return (
    <header className={styles.artifactHeader}>
      <div className={styles.artifactHeading}>
        <ChatShellIcon name={kind === "web" ? "web-output" : "ad-canvas"} size={12} />
        {renaming ? (
          <input
            aria-label="Rename artifact title"
            className={styles.artifactHeadingRenameInput}
            onBlur={commitRename}
            onChange={(event) => setDraftTitle(event.target.value)}
            onKeyDown={handleRenameKeyDown}
            ref={renameInputRef}
            value={draftTitle}
          />
        ) : (
          <span>{title}</span>
        )}
        <div className={styles.artifactActionMenuAnchor} ref={artifactActionMenuRef}>
          <button
            aria-expanded={artifactActionMenuOpen}
            aria-haspopup="menu"
            aria-label="More artifact actions"
            className={`${styles.artifactHeadingMenuButton} ${artifactActionMenuOpen ? styles.artifactHeadingMenuButtonActive : ""}`}
            onClick={toggleActions}
            type="button"
          >
            <EllipsisIcon
              absoluteStrokeWidth
              aria-hidden="true"
              size={14}
              strokeWidth={1.25}
            />
          </button>
          {artifactActionMenuOpen ? (
            <ArtifactActionMenu
              onRename={beginRename}
              onRequestAction={requestArtifactAction}
              onSelectVersion={selectVersion}
              onVersionsOpenChange={setVersionsOpen}
              redoDisabled={redoDisabled}
              selectedVersionId={selectedVersionId}
              undoDisabled={undoDisabled}
              versionsOpen={versionsOpen}
            />
          ) : null}
        </div>
      </div>
      <div className={styles.artifactHeaderActions}>
        {kind === "ad" ? (
          <div className={styles.toolbarMenuAnchor} ref={zoomMenuRef}>
            <button
              aria-expanded={zoomMenuOpen}
              aria-haspopup="menu"
              className={styles.zoomButton}
              onClick={() => {
                closeArtifactActionMenu();
                sharingController.closeMenu();
                toggleZoomMenu();
              }}
              type="button"
            >
              <span>{activeZoom}</span>
              <ChevronDownIcon
                absoluteStrokeWidth
                aria-hidden="true"
                className={zoomMenuOpen ? styles.zoomChevronOpen : undefined}
                size={14}
                strokeWidth={1.25}
              />
            </button>
            {zoomMenuOpen ? (
              <div aria-label="Canvas zoom" className={`${styles.toolbarMenu} ${styles.toolbarMenuScrollable}`} role="menu">
                {ZOOM_LEVELS.map((option) => (
                  <button
                    aria-checked={activeZoom === option}
                    className={`${styles.toolbarMenuItem} ${activeZoom === option ? styles.toolbarMenuItemActive : ""}`}
                    key={option}
                    onClick={() => chooseZoom(option)}
                    role="menuitemradio"
                    type="button"
                  >
                    <span>{option}</span>
                    {activeZoom === option ? <CheckIcon aria-hidden="true" size={12} strokeWidth={1.5} /> : null}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        ) : (
          <div className={styles.toolbarMenuAnchor} ref={deviceMenuRef}>
            <button
              aria-expanded={deviceMenuOpen}
              aria-haspopup="menu"
              aria-label={`Preview device: ${device}`}
              className={styles.deviceButton}
              onClick={() => {
                closeArtifactActionMenu();
                sharingController.closeMenu();
                toggleDeviceMenu();
              }}
              type="button"
            >
              <PreviewDeviceIcon
                absoluteStrokeWidth
                aria-hidden="true"
                size={16}
                strokeWidth={1.25}
              />
              <ChatShellIcon name="chevron-down" size={8} />
            </button>
            {deviceMenuOpen ? (
              <div aria-label="Preview device" className={styles.toolbarMenu} role="menu">
                {PREVIEW_DEVICES.map((option) => (
                  <button
                    aria-checked={device === option}
                    className={`${styles.toolbarMenuItem} ${device === option ? styles.toolbarMenuItemActive : ""}`}
                    key={option}
                    onClick={() => chooseDevice(option)}
                    role="menuitemradio"
                    type="button"
                  >
                    <span>{option}</span>
                    {device === option ? <CheckIcon aria-hidden="true" size={12} strokeWidth={1.5} /> : null}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        )}
        <button
          aria-pressed={editing}
          className={`${styles.artifactActionButton} ${editing ? styles.artifactActionButtonActive : ""}`}
          onClick={onEdit}
          type="button"
        >
          <ChatShellIcon name={editing ? "pencil-ruler-knockout" : "pencil-ruler"} size={14} />
          <span>Edit</span>
        </button>
        {kind === "ad" ? (
          <div className={styles.toolbarMenuAnchor} ref={imageExportMenuRef}>
            <button
              aria-expanded={imageExportController.menuOpen}
              aria-haspopup="dialog"
              className={`${styles.artifactActionButton} ${styles.artifactShareButton}`}
              onClick={() => {
                closeArtifactActionMenu();
                closeToolbarMenus();
                sharingController.closeMenu();
                imageExportController.toggleMenu();
              }}
              type="button"
            >
              <DownloadIcon absoluteStrokeWidth aria-hidden="true" size={13} strokeWidth={1.5} />
              Export
            </button>
            {imageExportController.menuOpen ? <ImageExportMenu controller={imageExportController} exportPreview={exportPreview} exportStatus={exportStatus} onRequestExportPreview={onRequestExportPreview} /> : null}
          </div>
        ) : (
          <div className={styles.toolbarMenuAnchor} ref={sharingMenuRef}>
            <button
              aria-expanded={sharingController.menuOpen}
              aria-haspopup="dialog"
              className={`${styles.artifactActionButton} ${styles.artifactShareButton}`}
              onClick={() => {
                closeArtifactActionMenu();
                closeToolbarMenus();
                imageExportController.closeMenu();
                sharingController.toggleMenu();
              }}
              type="button"
            >
              Share
            </button>
            {sharingController.menuOpen ? <ArtifactShareMenu controller={sharingController} /> : null}
          </div>
        )}
      </div>
    </header>
  );
}
