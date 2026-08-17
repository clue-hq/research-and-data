import {
  ArchiveIcon,
  CopyIcon,
  PencilIcon,
  Trash2Icon,
  type LucideIcon,
} from "lucide-react";
import type { ChatSessionAction } from "../model/chat-session-actions";
import styles from "./chat-shell.module.css";

function SessionMenuIcon({ icon: Icon }: { icon: LucideIcon }) {
  return (
    <Icon
      absoluteStrokeWidth
      aria-hidden="true"
      className={`${styles.artifactMenuIcon} ${styles.chatSessionMenuIcon}`}
      size={14}
      strokeWidth={1}
    />
  );
}

function SessionAction({
  action,
  destructive = false,
  icon,
  label,
  onSelect,
}: {
  action: ChatSessionAction;
  destructive?: boolean;
  icon: LucideIcon;
  label: string;
  onSelect: (action: ChatSessionAction) => void;
}) {
  return (
    <button
      className={`${styles.artifactMenuItem} ${destructive ? styles.artifactMenuItemDestructive : ""}`}
      onClick={() => onSelect(action)}
      role="menuitem"
      type="button"
    >
      <SessionMenuIcon icon={icon} />
      <span>{label}</span>
    </button>
  );
}

export function ChatSessionActionMenu({
  onCopySessionId,
  onRename,
  onRequestAction,
}: {
  onCopySessionId: () => void;
  onRename: () => void;
  onRequestAction: (action: ChatSessionAction) => void;
}) {
  return (
    <div
      aria-label="Chat session actions"
      className={`${styles.artifactActionMenu} ${styles.chatSessionMenu}`}
      role="menu"
    >
      <button className={styles.artifactMenuItem} onClick={onRename} role="menuitem" type="button">
        <SessionMenuIcon icon={PencilIcon} />
        <span>Rename chat</span>
      </button>
      <SessionAction action="archive" icon={ArchiveIcon} label="Archive chat" onSelect={onRequestAction} />

      <div aria-hidden="true" className={styles.artifactMenuSeparator} />

      <button className={styles.artifactMenuItem} onClick={onCopySessionId} role="menuitem" type="button">
        <SessionMenuIcon icon={CopyIcon} />
        <span>Copy session ID</span>
      </button>

      <div aria-hidden="true" className={styles.artifactMenuSeparator} />

      <SessionAction
        action="delete"
        destructive
        icon={Trash2Icon}
        label="Delete chat"
        onSelect={onRequestAction}
      />
    </div>
  );
}
