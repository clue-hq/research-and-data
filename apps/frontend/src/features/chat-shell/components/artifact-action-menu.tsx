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
import type { ArtifactActionRequest } from "../model/artifact-actions";
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
  label,
  onSelect,
  shortcut,
}: {
  action: ArtifactActionRequest;
  destructive?: boolean;
  label: string;
  onSelect: (action: ArtifactActionRequest) => void;
  shortcut?: string;
}) {
  return (
    <button
      className={`${styles.artifactMenuItem} ${destructive ? styles.artifactMenuItemDestructive : ""}`}
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
  selectedVersionId,
  versionsOpen,
}: {
  onRename: () => void;
  onRequestAction: (action: ArtifactActionRequest) => void;
  onSelectVersion: (versionId: string) => void;
  onVersionsOpenChange: (open: boolean) => void;
  selectedVersionId: string;
  versionsOpen: boolean;
}) {
  const versionOptions = [
    { id: "current", label: "Current version" },
    { id: "version-3", label: "Version 3" },
    { id: "version-2", label: "Version 2" },
    { id: "version-1", label: "Version 1" },
  ];

  return (
    <div aria-label="Artifact actions" className={styles.artifactActionMenu} role="menu">
      <button className={styles.artifactMenuItem} onClick={onRename} role="menuitem" type="button">
        <ArtifactActionIcon name="rename" />
        <span>Rename</span>
      </button>
      <MenuAction action="duplicate" label="Duplicate" onSelect={onRequestAction} />

      <div aria-hidden="true" className={styles.artifactMenuSeparator} />

      <MenuAction action="undo" label="Undo" onSelect={onRequestAction} shortcut="⌘Z" />
      <MenuAction action="redo" label="Redo" onSelect={onRequestAction} shortcut="⇧⌘Z" />
      <div
        className={styles.artifactVersionsRow}
        onMouseEnter={() => onVersionsOpenChange(true)}
      >
        <button
          aria-expanded={versionsOpen}
          aria-haspopup="menu"
          className={`${styles.artifactMenuItem} ${versionsOpen ? styles.artifactMenuItemActive : ""}`}
          onClick={() => onVersionsOpenChange(true)}
          onKeyDown={(event) => {
            if (event.key === "ArrowRight") onVersionsOpenChange(true);
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
                aria-checked={selectedVersionId === version.id}
                className={`${styles.artifactVersionItem} ${selectedVersionId === version.id ? styles.artifactVersionItemActive : ""}`}
                key={version.id}
                onClick={() => onSelectVersion(version.id)}
                role="menuitemradio"
                type="button"
              >
                <span>{version.label}</span>
                {selectedVersionId === version.id ? (
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
