"use client";

import { EllipsisIcon } from "lucide-react";
import { useChatSessionMenuController } from "../hooks/use-chat-session-menu-controller";
import { ChatSessionActionMenu } from "./chat-session-action-menu";
import { ChatShellIcon } from "./chat-shell-icon";
import styles from "./chat-shell.module.css";

// Lifted from the branch's chat-shell-header, adapted for Phase C: the
// session-menu controller's stub event bus is replaced with the injected
// onRename/onArchive callbacks (wired to the production chat controller by
// the chat surface). projectId stays on the interface for the callers'
// route context but is no longer read here — it only ever rode the stub
// bus's event payloads.

export function ChatShellHeader({
  chatId,
  onArchive,
  onRename,
  onToggleArtifactPanel,
  panelOpen,
  title = "Untitled",
}: {
  chatId?: string;
  onArchive: () => Promise<void> | void;
  onRename: (title: string) => Promise<void> | void;
  onToggleArtifactPanel: () => void;
  panelOpen: boolean;
  projectId?: string;
  title?: string;
}) {
  const {
    commitRename,
    copySessionId,
    draftTitle,
    handleRenameKeyDown,
    inputRef,
    menuOpen,
    menuRef,
    renaming,
    requestAction,
    setDraftTitle,
    startRename,
    statusMessage,
    toggleMenu,
  } = useChatSessionMenuController({
    chatId,
    onArchive,
    onRename,
    title,
  });

  return (
    <header className={styles.chatHeader}>
      <div className={styles.chatTitleCluster}>
        {renaming ? (
          <input
            aria-label="Rename chat session"
            className={styles.chatTitleRenameInput}
            onBlur={commitRename}
            onChange={(event) => setDraftTitle(event.target.value)}
            onKeyDown={handleRenameKeyDown}
            ref={inputRef}
            value={draftTitle}
          />
        ) : (
          <>
            <span className={styles.chatTitleLabel} title={title}>{title}</span>
            <div className={styles.chatTitleMenuAnchor} ref={menuRef}>
              <button
                aria-expanded={menuOpen}
                aria-haspopup="menu"
                aria-label="Chat session actions"
                className={`${styles.chatSessionMenuButton} ${menuOpen ? styles.chatSessionMenuButtonActive : ""}`}
                onClick={toggleMenu}
                type="button"
              >
                <EllipsisIcon
                  absoluteStrokeWidth
                  aria-hidden="true"
                  size={14}
                  strokeWidth={1.25}
                />
              </button>
              {menuOpen ? (
                <ChatSessionActionMenu
                  onCopySessionId={copySessionId}
                  onRename={startRename}
                  onRequestAction={requestAction}
                />
              ) : null}
            </div>
          </>
        )}
        <span aria-live="polite" className={styles.srOnly}>{statusMessage}</span>
      </div>
      {!panelOpen ? (
        <button
          aria-expanded={false}
          aria-label="Open artifact panel"
          className={styles.iconButton}
          onClick={onToggleArtifactPanel}
          type="button"
        >
          <ChatShellIcon name="canvas-panel-open" size={12} />
        </button>
      ) : null}
    </header>
  );
}
