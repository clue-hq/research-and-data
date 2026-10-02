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
import {
  useArtifactToolbarController,
  type ArtifactPageOption,
  type ArtifactPreviewDevice,
} from "../hooks/use-artifact-toolbar-controller";
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
  editDisabled = false,
  editDisabledReason = null,
  activePageId,
  device,
  documentId,
  editing,
  exportPreview,
  exportStatus,
  kind,
  onDeviceChange,
  onEdit,
  onPageChange,
  onRename,
  onRequestExportPreview,
  onZoomChange,
  pages,
  redoDisabled,
  title,
  undoDisabled,
  zoom,
}: {
  /**
   * Task 4 (scene live-streaming rung A): the agent-run lock refuses ENTRY into
   * edit mode while a design turn is running on the open document — offering a
   * pressed Edit that reveals an entirely inert inspector would be a promise the
   * platform cannot keep, and the backend would 409 every write behind it.
   *
   * Leaving edit mode is deliberately never refused (the caller decides), so a
   * lock engaging mid-edit cannot trap the user in a dock they cannot close.
   */
  editDisabled?: boolean;
  /** Task 4: the lock's own ratified sentence, on the pill itself. No new
   * chrome is invented for it — the button already has a hover/AT surface, and
   * the same sentence is in the inspector's note line beside it. */
  editDisabledReason?: string | null;
  /** F5 task 18: the page the canvas is rendering. Present → the web editing
   * session owns the value; absent leaves the toolbar controller's own local
   * value. */
  activePageId?: string | null;
  /** The preview device to display. Present → the artifact stage owns the
   * value (it also drives the web canvas viewport width); absent leaves the
   * toolbar controller's own local value. */
  device?: ArtifactPreviewDevice | null;
  /** F5 task 13: the design document behind the artifact — what the Share
   * menu publishes. Absent while the stage has no document, which leaves
   * publishing unavailable rather than faked. */
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
  /** A device the user picked from the menu, reported to the artifact stage —
   * which owns the value and hands it back through `device`. The AD branch
   * renders the zoom menu instead and never touches either. */
  onDeviceChange?: (device: ArtifactPreviewDevice) => void;
  onEdit: () => void;
  /** F5 task 18: a page the user picked from the switcher, reported to the web
   * editing session — which owns the value and hands it back through
   * `activePageId`. */
  onPageChange?: (pageId: string) => void;
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
  /** F5 task 18: the active web document's pages. Empty/absent → the switcher
   * is not rendered at all (an ad, or a document with no pages yet). */
  pages?: readonly ArtifactPageOption[];
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
  } = useArtifactSharingController({ documentId, kind, title });
  const {
    controller: imageExportController,
    menuRef: imageExportMenuRef,
  } = useImageExportController({ title });
  const {
    activePage,
    activePageId: shownPageId,
    chooseDevice,
    choosePage,
    chooseZoom,
    closeMenus: closeToolbarMenus,
    device: activeDevice,
    deviceMenuOpen,
    deviceMenuRef,
    pageMenuOpen,
    pageMenuRef,
    toggleDeviceMenu,
    togglePageMenu,
    toggleZoomMenu,
    zoom: activeZoom,
    zoomMenuOpen,
    zoomMenuRef,
    // AD2.8: zoom is LIFTED — the ad session owns it, because the same value
    // has to drive the canvas viewport. The device choice is lifted the same
    // way: the artifact stage owns it, because it also sets the web canvas's
    // viewport width. F5 task 18 lifts the page the same way again — the web
    // editing session owns it, because it also drives the render fetch.
  } = useArtifactToolbarController({
    activePageId,
    device,
    onDeviceChange,
    onPageChange,
    onZoomChange,
    pages,
    zoom,
  });
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
  const PreviewDeviceIcon = PREVIEW_DEVICE_ICONS[activeDevice];

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
        {/* FLAGGED F5 T18: no designed slot in the dummy frontend for a page
         * switcher — minimal neutral control pending founder/design ruling.
         * Styled as the device/zoom menus already are, so it reads as one of
         * them rather than as invented chrome.
         *
         * F5 T19 (founder ruling after T18): TWO pages, not one. A single-page
         * site has nothing to switch to, so its header stays exactly as it
         * shipped — the switcher appears the moment a site becomes plural. */}
        {kind === "web" && pages && pages.length >= 2 ? (
          <div className={styles.toolbarMenuAnchor} ref={pageMenuRef}>
            <button
              aria-expanded={pageMenuOpen}
              aria-haspopup="menu"
              aria-label={`Page: ${activePage?.name ?? ""}`}
              className={styles.zoomButton}
              onClick={() => {
                closeArtifactActionMenu();
                sharingController.closeMenu();
                imageExportController.closeMenu();
                togglePageMenu();
              }}
              type="button"
            >
              <span>{activePage?.name ?? ""}</span>
              <ChevronDownIcon
                absoluteStrokeWidth
                aria-hidden="true"
                className={pageMenuOpen ? styles.zoomChevronOpen : undefined}
                size={14}
                strokeWidth={1.25}
              />
            </button>
            {pageMenuOpen ? (
              <div aria-label="Page" className={`${styles.toolbarMenu} ${styles.toolbarMenuScrollable}`} role="menu">
                {pages.map((option) => (
                  <button
                    aria-checked={shownPageId === option.id}
                    className={`${styles.toolbarMenuItem} ${shownPageId === option.id ? styles.toolbarMenuItemActive : ""}`}
                    key={option.id}
                    onClick={() => choosePage(option.id)}
                    role="menuitemradio"
                    type="button"
                  >
                    <span>
                      {option.name}
                      <span className={styles.toolbarMenuItemHint}>{option.route}</span>
                    </span>
                    {shownPageId === option.id ? <CheckIcon aria-hidden="true" size={12} strokeWidth={1.5} /> : null}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
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
              aria-label={`Preview device: ${activeDevice}`}
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
                    aria-checked={activeDevice === option}
                    className={`${styles.toolbarMenuItem} ${activeDevice === option ? styles.toolbarMenuItemActive : ""}`}
                    key={option}
                    onClick={() => chooseDevice(option)}
                    role="menuitemradio"
                    type="button"
                  >
                    <span>{option}</span>
                    {activeDevice === option ? <CheckIcon aria-hidden="true" size={12} strokeWidth={1.5} /> : null}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        )}
        <button
          aria-pressed={editing}
          className={`${styles.artifactActionButton} ${editing ? styles.artifactActionButtonActive : ""}`}
          disabled={editDisabled}
          onClick={onEdit}
          // The reason rides the pill itself rather than a new badge: this
          // repo's presentation-truth rule forbids inventing chrome for data
          // with no designed slot, and the same sentence is already on screen
          // in the inspector's note line.
          title={editDisabled ? (editDisabledReason ?? undefined) : undefined}
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
