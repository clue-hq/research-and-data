"use client";

import {
  type KeyboardEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ChatSessionAction } from "../model/chat-session-actions";

// Adapted from the branch's use-chat-session-menu-controller. The source's
// three window.dispatchEvent CustomEvents (clue:chat-session-rename,
// clue:chat-session-action-request, clue:chat-session-id-copy) were a stub
// bus with no listener in either tree — replaced with injected callbacks
// (onRename / onArchive) that Phase C wires to the production chat
// controller's renameThread/archiveThread. Copy-session-id keeps its
// clipboard write + aria-live message.
//
// The interaction semantics live in the pure transition function so
// node:test drives them directly (same pattern as use-editor-shell-controller):
// the hook applies transitions and runs the returned effect — never inside a
// state updater, where StrictMode's double-invoke would double-fire the
// backend calls.

export interface ChatSessionMenuState {
  draftTitle: string;
  menuOpen: boolean;
  renameCancelled: boolean;
  renaming: boolean;
  statusMessage: string;
}

export type ChatSessionMenuEvent =
  | { type: "toggle-menu" }
  | { type: "dismiss" }
  | { type: "start-rename" }
  | { draft: string; type: "set-draft" }
  | { type: "cancel-rename" }
  | { type: "commit-rename" }
  | { action: ChatSessionAction; type: "session-action" }
  | { message: string; type: "copy-status" };

export type ChatSessionMenuEffect =
  | { kind: "archive" }
  | { kind: "rename"; title: string };

export interface ChatSessionMenuTransition {
  effect: ChatSessionMenuEffect | null;
  state: ChatSessionMenuState;
}

export function createInitialChatSessionMenuState(
  title: string,
): ChatSessionMenuState {
  return {
    draftTitle: title,
    menuOpen: false,
    renameCancelled: false,
    renaming: false,
    statusMessage: "",
  };
}

export function transitionChatSessionMenu(
  state: ChatSessionMenuState,
  event: ChatSessionMenuEvent,
  title: string,
): ChatSessionMenuTransition {
  switch (event.type) {
    case "toggle-menu":
      return { effect: null, state: { ...state, menuOpen: !state.menuOpen } };
    case "dismiss":
      if (!state.menuOpen) return { effect: null, state };
      return { effect: null, state: { ...state, menuOpen: false } };
    case "start-rename":
      return {
        effect: null,
        state: {
          ...state,
          draftTitle: title,
          menuOpen: false,
          renameCancelled: false,
          renaming: true,
        },
      };
    case "set-draft":
      return { effect: null, state: { ...state, draftTitle: event.draft } };
    case "cancel-rename":
      return {
        effect: null,
        state: {
          ...state,
          draftTitle: title,
          renameCancelled: true,
          renaming: false,
        },
      };
    case "commit-rename": {
      if (state.renameCancelled) {
        // The input's blur fires right after an Escape-cancel; it must not
        // re-commit the abandoned draft.
        return { effect: null, state: { ...state, renameCancelled: false } };
      }
      if (!state.renaming) return { effect: null, state };
      const nextTitle = state.draftTitle.trim();
      if (!nextTitle) {
        return {
          effect: null,
          state: { ...state, draftTitle: title, renaming: false },
        };
      }
      return {
        effect: { kind: "rename", title: nextTitle },
        state: { ...state, renaming: false },
      };
    }
    case "session-action": {
      if (event.action === "archive") {
        return {
          effect: { kind: "archive" },
          state: {
            ...state,
            menuOpen: false,
            statusMessage: "Archive requested",
          },
        };
      }
      // R5 (founder ruling 2026-08-17): Delete renders with its destructive
      // styling but is inert — no callback, no backend call, and no aria-live
      // message (announcing "requested" would be a false success claim).
      return { effect: null, state: { ...state, menuOpen: false } };
    }
    case "copy-status":
      return {
        effect: null,
        state: { ...state, menuOpen: false, statusMessage: event.message },
      };
  }
}

export function useChatSessionMenuController({
  chatId,
  onArchive,
  onRename,
  title,
}: {
  chatId?: string;
  onArchive: () => Promise<void> | void;
  onRename: (title: string) => Promise<void> | void;
  title: string;
}) {
  const [state, setState] = useState(() =>
    createInitialChatSessionMenuState(title),
  );
  const inputRef = useRef<HTMLInputElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  // Every state change flows through apply(), which keeps this ref in sync —
  // no render-time ref write needed (react-hooks/refs).
  const stateRef = useRef(state);

  const apply = useCallback(
    (event: ChatSessionMenuEvent) => {
      const { effect, state: next } = transitionChatSessionMenu(
        stateRef.current,
        event,
        title,
      );
      stateRef.current = next;
      setState(next);
      if (effect?.kind === "rename") void onRename(effect.title);
      if (effect?.kind === "archive") void onArchive();
    },
    [onArchive, onRename, title],
  );

  useEffect(() => {
    if (!state.renaming) return;
    inputRef.current?.focus();
    inputRef.current?.select();
  }, [state.renaming]);

  useEffect(() => {
    const dismissOnPointerDown = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) {
        apply({ type: "dismiss" });
      }
    };
    const dismissOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") apply({ type: "dismiss" });
    };

    document.addEventListener("pointerdown", dismissOnPointerDown);
    document.addEventListener("keydown", dismissOnEscape);
    return () => {
      document.removeEventListener("pointerdown", dismissOnPointerDown);
      document.removeEventListener("keydown", dismissOnEscape);
    };
  }, [apply]);

  const closeMenu = useCallback(() => apply({ type: "dismiss" }), [apply]);
  const toggleMenu = useCallback(() => apply({ type: "toggle-menu" }), [apply]);
  const startRename = useCallback(
    () => apply({ type: "start-rename" }),
    [apply],
  );
  const cancelRename = useCallback(
    () => apply({ type: "cancel-rename" }),
    [apply],
  );
  const commitRename = useCallback(
    () => apply({ type: "commit-rename" }),
    [apply],
  );
  const setDraftTitle = useCallback(
    (draft: string) => apply({ draft, type: "set-draft" }),
    [apply],
  );
  const requestAction = useCallback(
    (action: ChatSessionAction) => apply({ action, type: "session-action" }),
    [apply],
  );

  const handleRenameKeyDown = useCallback(
    (event: KeyboardEvent<HTMLInputElement>) => {
      if (event.key === "Enter") commitRename();
      if (event.key === "Escape") cancelRename();
    },
    [cancelRename, commitRename],
  );

  const copySessionId = useCallback(async () => {
    if (!chatId) {
      apply({ message: "Session ID is not available", type: "copy-status" });
      return;
    }

    try {
      if (!navigator.clipboard?.writeText) {
        throw new Error("Clipboard API unavailable");
      }
      await navigator.clipboard.writeText(chatId);
      apply({ message: "Session ID copied", type: "copy-status" });
    } catch {
      apply({ message: "Unable to copy session ID", type: "copy-status" });
    }
  }, [apply, chatId]);

  return useMemo(
    () => ({
      cancelRename,
      closeMenu,
      commitRename,
      copySessionId,
      draftTitle: state.draftTitle,
      handleRenameKeyDown,
      inputRef,
      menuOpen: state.menuOpen,
      menuRef,
      renaming: state.renaming,
      requestAction,
      setDraftTitle,
      startRename,
      statusMessage: state.statusMessage,
      toggleMenu,
    }),
    [
      cancelRename,
      closeMenu,
      commitRename,
      copySessionId,
      handleRenameKeyDown,
      requestAction,
      setDraftTitle,
      startRename,
      state,
      toggleMenu,
    ],
  );
}
