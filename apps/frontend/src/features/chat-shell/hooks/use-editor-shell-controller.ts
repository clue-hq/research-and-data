"use client";

import { useCallback, useEffect, useMemo, useReducer } from "react";
import type {
  ChatShellArtifactKind,
  ChatShellInspectorSelection,
  ChatShellOpenArtifact,
} from "../model/chat-shell";

// The editor half of the branch's use-chat-shell-controller: tabs, maximize,
// editing, and inspector selection. The chat/gallery surface machine is not
// carried over — the artifact route is always the artifact surface, so closing
// the last tab leaves the empty artifact state (activeArtifactId null), never
// a gallery fallback. There is deliberately no default-tab fabrication: the
// artifact list is the source of tab truth.

export interface EditorShellInitialState {
  artifactId?: string;
  editing?: boolean;
  inspectorSelection?: ChatShellInspectorSelection;
  openArtifacts?: ChatShellOpenArtifact[];
  projectId?: string;
}

export interface EditorShellState {
  activeArtifactId: string | null;
  artifactMaximized: boolean;
  editing: boolean;
  inspectorSelection: ChatShellInspectorSelection;
  openArtifacts: ChatShellOpenArtifact[];
}

export type EditorShellAction =
  | { type: "activate-artifact"; artifactId: string }
  | { type: "open-artifact"; artifact: ChatShellOpenArtifact }
  | { type: "close-artifact"; artifactId: string }
  | { type: "rename-artifact"; artifactId: string; title: string }
  | { type: "toggle-maximized" }
  | { type: "restore-maximized" }
  | { type: "set-editing"; editing: boolean }
  | { type: "select-inspector-element"; selection: ChatShellInspectorSelection };

export function createInitialEditorShellState(
  initial: EditorShellInitialState,
): EditorShellState {
  const openArtifacts = initial.openArtifacts ?? [];
  return {
    activeArtifactId: initial.artifactId ?? openArtifacts[0]?.id ?? null,
    artifactMaximized: false,
    editing: Boolean(initial.editing),
    inspectorSelection: initial.inspectorSelection ?? "canvas",
    openArtifacts,
  };
}

export function editorShellReducer(
  state: EditorShellState,
  action: EditorShellAction,
): EditorShellState {
  switch (action.type) {
    case "activate-artifact":
      return {
        ...state,
        activeArtifactId: action.artifactId,
        inspectorSelection: "canvas",
      };
    case "open-artifact":
      return {
        ...state,
        activeArtifactId: action.artifact.id,
        editing: false,
        inspectorSelection: "canvas",
        openArtifacts: state.openArtifacts.some(
          (candidate) => candidate.id === action.artifact.id,
        )
          ? state.openArtifacts
          : [...state.openArtifacts, action.artifact],
      };
    case "close-artifact": {
      const closedIndex = state.openArtifacts.findIndex(
        (artifact) => artifact.id === action.artifactId,
      );
      const remaining = state.openArtifacts.filter(
        (artifact) => artifact.id !== action.artifactId,
      );
      if (state.activeArtifactId !== action.artifactId) {
        return { ...state, openArtifacts: remaining };
      }
      const nextArtifact = remaining[closedIndex] ?? remaining[closedIndex - 1] ?? null;
      return {
        ...state,
        activeArtifactId: nextArtifact?.id ?? null,
        editing: false,
        inspectorSelection: "canvas",
        openArtifacts: remaining,
      };
    }
    case "rename-artifact": {
      const nextTitle = action.title.trim();
      if (!nextTitle) return state;
      return {
        ...state,
        openArtifacts: state.openArtifacts.map((artifact) =>
          artifact.id === action.artifactId
            ? { ...artifact, title: nextTitle }
            : artifact,
        ),
      };
    }
    case "toggle-maximized":
      return { ...state, artifactMaximized: !state.artifactMaximized };
    case "restore-maximized":
      return { ...state, artifactMaximized: false };
    case "set-editing":
      return {
        ...state,
        editing: action.editing,
        inspectorSelection: action.editing ? "canvas" : state.inspectorSelection,
      };
    case "select-inspector-element":
      return { ...state, inspectorSelection: action.selection };
  }
}

export interface EditorShellController {
  activateArtifact: (artifactId: string) => void;
  activeArtifactId: string | null;
  artifactId?: string;
  artifactKind: ChatShellArtifactKind | null;
  artifactMaximized: boolean;
  artifactTitle: string;
  closeArtifact: (artifactId: string) => void;
  editing: boolean;
  inspectorSelection: ChatShellInspectorSelection;
  openArtifact: (artifact: ChatShellOpenArtifact) => void;
  openArtifacts: ChatShellOpenArtifact[];
  projectId?: string;
  selectInspectorElement: (selection: ChatShellInspectorSelection) => void;
  setArtifactTitleFor: (artifactId: string, title: string) => void;
  setEditing: (editing: boolean) => void;
  toggleArtifactMaximized: () => void;
}

export function useEditorShellController(
  initial: EditorShellInitialState = {},
): EditorShellController {
  const [state, dispatch] = useReducer(
    editorShellReducer,
    initial,
    createInitialEditorShellState,
  );

  const activeArtifact =
    state.openArtifacts.find(
      (artifact) => artifact.id === state.activeArtifactId,
    ) ?? null;

  const activateArtifact = useCallback((artifactId: string) => {
    dispatch({ artifactId, type: "activate-artifact" });
  }, []);
  const openArtifact = useCallback((artifact: ChatShellOpenArtifact) => {
    dispatch({ artifact, type: "open-artifact" });
  }, []);
  const closeArtifact = useCallback((artifactId: string) => {
    dispatch({ artifactId, type: "close-artifact" });
  }, []);
  const setArtifactTitleFor = useCallback((artifactId: string, title: string) => {
    dispatch({ artifactId, title, type: "rename-artifact" });
  }, []);
  const toggleArtifactMaximized = useCallback(() => {
    dispatch({ type: "toggle-maximized" });
  }, []);
  const setEditing = useCallback((editing: boolean) => {
    dispatch({ editing, type: "set-editing" });
  }, []);
  const selectInspectorElement = useCallback(
    (selection: ChatShellInspectorSelection) => {
      dispatch({ selection, type: "select-inspector-element" });
    },
    [],
  );

  useEffect(() => {
    if (!state.artifactMaximized) return;

    const restoreOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        dispatch({ type: "restore-maximized" });
      }
    };

    document.addEventListener("keydown", restoreOnEscape);
    return () => document.removeEventListener("keydown", restoreOnEscape);
  }, [state.artifactMaximized]);

  return useMemo(
    () => ({
      activateArtifact,
      activeArtifactId: state.activeArtifactId,
      artifactId: state.activeArtifactId ?? undefined,
      artifactKind: activeArtifact?.kind ?? null,
      artifactMaximized: state.artifactMaximized,
      artifactTitle: activeArtifact?.title ?? "Web output",
      closeArtifact,
      editing: state.editing,
      inspectorSelection: state.inspectorSelection,
      openArtifact,
      openArtifacts: state.openArtifacts,
      projectId: initial.projectId,
      selectInspectorElement,
      setArtifactTitleFor,
      setEditing,
      toggleArtifactMaximized,
    }),
    [
      activateArtifact,
      activeArtifact,
      closeArtifact,
      initial.projectId,
      openArtifact,
      selectInspectorElement,
      setArtifactTitleFor,
      setEditing,
      state,
      toggleArtifactMaximized,
    ],
  );
}
