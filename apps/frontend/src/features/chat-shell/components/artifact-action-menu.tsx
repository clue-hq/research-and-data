import {
  ArchiveIcon,
  ChevronRightIcon,
  CopyIcon,
  HistoryIcon,
  PencilIcon,
  Redo2Icon,
  Trash2Icon,
  Undo2Icon,
  type LucideIcon,
} from "lucide-react";
import type { ArtifactActionRequest, ArtifactVersionsBinding } from "../model/artifact-actions";
import styles from "./chat-shell.module.css";

const ARTIFACT_ACTION_ICONS = {
  archive: ArchiveIcon,
  delete: Trash2Icon,
  duplicate: CopyIcon,
  redo: Redo2Icon,
  rename: PencilIcon,
  undo: Undo2Icon,
  versions: HistoryIcon,
} satisfies Record<ArtifactActionRequest | "rename", LucideIcon>;

type ArtifactActionIconName = keyof typeof ARTIFACT_ACTION_ICONS;

function ArtifactActionIcon({ name }: { name: ArtifactActionIconName }) {
  const Icon = ARTIFACT_ACTION_ICONS[name];

  return (
    <Icon
      absoluteStrokeWidth
      aria-hidden="true"
      className={styles.artifactMenuIcon}
      size={16}
      strokeWidth={1.25}
    />
  );
}

function MenuAction({
  action,
  destructive = false,
  disabled = false,
  label,
  onSelect,
  shortcut,
}: {
  action: ArtifactActionRequest;
  destructive?: boolean;
  /** W3.4: empty-stack undo/redo disable (native button semantics). */
  disabled?: boolean;
  label: string;
  onSelect: (action: ArtifactActionRequest) => void;
  shortcut?: string;
}) {
  return (
    <button
      className={`${styles.artifactMenuItem} ${destructive ? styles.artifactMenuItemDestructive : ""}`}
      disabled={disabled}
      onClick={() => onSelect(action)}
      role="menuitem"
      type="button"
    >
      <ArtifactActionIcon name={action} />
      <span>{label}</span>
      {shortcut ? <span className={styles.artifactMenuShortcut}>{shortcut}</span> : null}
    </button>
  );
}

export function ArtifactActionMenu({
  onRename,
  onRequestAction,
  onSelectVersion,
  onVersionsOpenChange,
  redoDisabled = false,
  renameLockNote = null,
  selectedVersionId,
  undoDisabled = false,
  versions = null,
  versionsOpen,
}: {
  onRename: () => void;
  onRequestAction: (action: ArtifactActionRequest) => void;
  onSelectVersion: (versionId: string) => void;
  onVersionsOpenChange: (open: boolean) => void;
  /** W3.4: driven by the loaded document's redoDepth (empty stack → true). */
  redoDisabled?: boolean;
  /** K1-5 (founder ruling 2026-10-16): a design run drives the document, so
   * Rename is inert and this sentence sits under it. Absent leaves Rename live. */
  renameLockNote?: string | null;
  selectedVersionId: string;
  /** W3.4: driven by the loaded document's undoDepth (empty stack → true). */
  undoDisabled?: boolean;
  /** C9: a real version list (sites); absent keeps the existing list. */
  versions?: ArtifactVersionsBinding | null;
  versionsOpen: boolean;
}) {
  const versionOptions = versions
    ? versions.options
    : [
        { id: "current", label: "Current version" },
        { id: "version-3", label: "Version 3" },
        { id: "version-2", label: "Version 2" },
        { id: "version-1", label: "Version 1" },
      ];
  const shownVersionId = versions ? versions.selectedId : selectedVersionId;
  const openVersions = () => {
    if (versions && !versionsOpen) versions.open();
    onVersionsOpenChange(true);
  };
  const chooseVersion = (versionId: string) => (versions ? versions.select(versionId) : onSelectVersion(versionId));

  return (
    <div aria-label="Artifact actions" className={styles.artifactActionMenu} role="menu">
      <button
        className={styles.artifactMenuItem}
        disabled={renameLockNote !== null}
        onClick={onRename}
        role="menuitem"
        type="button"
      >
        <ArtifactActionIcon name="rename" />
        <span>Rename</span>
      </button>
      {renameLockNote !== null ? (
        <p className={styles.artifactMenuNote}>{renameLockNote}</p>
      ) : null}
      <MenuAction action="duplicate" label="Duplicate" onSelect={onRequestAction} />

      <div aria-hidden="true" className={styles.artifactMenuSeparator} />

      <MenuAction action="undo" disabled={undoDisabled} label="Undo" onSelect={onRequestAction} shortcut="⌘Z" />
      <MenuAction action="redo" disabled={redoDisabled} label="Redo" onSelect={onRequestAction} shortcut="⇧⌘Z" />
      <div
        className={styles.artifactVersionsRow}
        onMouseEnter={() => openVersions()}
      >
        <button
          aria-expanded={versionsOpen}
          aria-haspopup="menu"
          className={`${styles.artifactMenuItem} ${versionsOpen ? styles.artifactMenuItemActive : ""}`}
          onClick={() => openVersions()}
          onKeyDown={(event) => {
            if (event.key === "ArrowRight") openVersions();
          }}
          role="menuitem"
          type="button"
        >
          <ArtifactActionIcon name="versions" />
          <span>Versions</span>
          <ChevronRightIcon
            absoluteStrokeWidth
            aria-hidden="true"
            className={styles.artifactMenuChevron}
            size={12}
            strokeWidth={1.25}
          />
        </button>
        {versionsOpen ? (
          <div aria-label="Versions" className={styles.artifactVersionsMenu} role="menu">
            <div className={styles.artifactVersionsLabel}>Versions</div>
            {versionOptions.map((version) => (
              <button
                aria-checked={shownVersionId === version.id}
                className={`${styles.artifactVersionItem} ${shownVersionId === version.id ? styles.artifactVersionItemActive : ""}`}
                key={version.id}
                onClick={() => chooseVersion(version.id)}
                role="menuitemradio"
                type="button"
              >
                <span>{version.label}</span>
                {shownVersionId === version.id ? (
                  <span className={styles.artifactVersionMeta}>Open</span>
                ) : null}
              </button>
            ))}
          </div>
        ) : null}
      </div>

      <div aria-hidden="true" className={styles.artifactMenuSeparator} />

      <MenuAction action="archive" label="Archive" onSelect={onRequestAction} />
      <MenuAction action="delete" destructive label="Delete" onSelect={onRequestAction} />
    </div>
  );
}
