"use client";

import { useCallback, useEffect, useMemo, useReducer } from "react";
import type {
  ChatShellArtifactKind,
  ChatShellInspectorSelection,
  ChatShellOpenArtifact,
} from "../model/chat-shell";

// The editor half of the branch's use-chat-shell-controller: tabs, maximize,
// editing, inspector selection, and the artifact/gallery surface pair. The
// chat surface is not carried over (platform chat owns it). Per the founder
// amendment of 2026-08-17 (W0.5), the gallery rides along as presentation-only
// chrome with the original semantics: closing the last tab falls back to the
// gallery surface, and an empty shell starts there. There is deliberately no
// default-tab fabrication: the artifact list is the source of tab truth.

// The target-accounts surface joins the pair as a third resting surface of the
// rail (the branch's own `ChatShellSurface` gained it the same way): it is not
// an artifact, carries no editing, and — like the gallery — never opens the
// editor dock.
export type EditorShellSurface = "artifact" | "gallery" | "target-accounts" | "plan";

export interface EditorShellInitialState {
  artifactId?: string;
  editing?: boolean;
  inspectorSelection?: ChatShellInspectorSelection;
  openArtifacts?: ChatShellOpenArtifact[];
  // Phase C (C-3): the chats route mounts the rail closed by default and
  // opens it from ?surface= pane state; the artifact route keeps the
  // default-open panel (full-width editor). `surface` lets a surface=web|ad
  // URL land on the artifact surface even before any artifact exists.
  panelOpen?: boolean;
  projectId?: string;
  surface?: EditorShellSurface;
}

export interface EditorShellState {
  activeArtifactId: string | null;
  artifactMaximized: boolean;
  editing: boolean;
  inspectorSelection: ChatShellInspectorSelection;
  openArtifacts: ChatShellOpenArtifact[];
  panelOpen: boolean;
  surface: EditorShellSurface;
}

export type EditorShellAction =
  | { type: "activate-artifact"; artifactId: string }
  | { type: "open-artifact"; artifact: ChatShellOpenArtifact }
  | { type: "open-plan" }
  | { type: "open-gallery" }
  | { type: "open-target-accounts" }
  | { type: "close-artifact"; artifactId: string }
  | { type: "rename-artifact"; artifactId: string; title: string }
  | { type: "toggle-panel" }
  | { type: "toggle-maximized" }
  | { type: "restore-maximized" }
  | { type: "set-editing"; editing: boolean }
  | { type: "select-inspector-element"; selection: ChatShellInspectorSelection };

export function createInitialEditorShellState(
  initial: EditorShellInitialState,
): EditorShellState {
  const openArtifacts = initial.openArtifacts ?? [];
  const activeArtifactId = initial.artifactId ?? openArtifacts[0]?.id ?? null;
  return {
    activeArtifactId,
    artifactMaximized: false,
    editing: Boolean(initial.editing),
    inspectorSelection: initial.inspectorSelection ?? "canvas",
    openArtifacts,
    panelOpen: initial.panelOpen ?? true,
    surface: initial.surface ?? (activeArtifactId ? "artifact" : "gallery"),
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
        panelOpen: true,
        surface: "artifact",
      };
    case "open-artifact":
      // Re-opening the tab that is already in front is a no-op. Resetting
      // edit mode and the selection here would throw a person out of an edit
      // they are in the middle of — which is what a feed refresh carrying their
      // own write did until 2026-09-20.
      if (
        state.activeArtifactId === action.artifact.id &&
        state.surface === "artifact" &&
        state.panelOpen
      ) {
        return state;
      }
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
        panelOpen: true,
        surface: "artifact",
      };
    case "open-plan":
      return { ...state, editing: false, panelOpen: true, surface: "plan" };
    case "open-gallery":
      return { ...state, editing: false, panelOpen: true, surface: "gallery" };
    case "open-target-accounts":
      return {
        ...state,
        editing: false,
        panelOpen: true,
        surface: "target-accounts",
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
        surface: nextArtifact ? "artifact" : "gallery",
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
    case "toggle-panel":
      // Mirrors the source controller: opening from the conversation lands on
      // the gallery; closing resets edit mode and the maximized stage.
      return state.panelOpen
        ? {
            ...state,
            artifactMaximized: false,
            editing: false,
            panelOpen: false,
          }
        : { ...state, editing: false, panelOpen: true, surface: "gallery" };
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
  openPlan: () => void;
  openGallery: () => void;
  openTargetAccounts: () => void;
  panelOpen: boolean;
  projectId?: string;
  toggleArtifactPanel: () => void;
  selectInspectorElement: (selection: ChatShellInspectorSelection) => void;
  surface: EditorShellSurface;
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
  const openPlan = useCallback(() => { dispatch({ type: "open-plan" }); }, []);
  const openGallery = useCallback(() => {
    dispatch({ type: "open-gallery" });
  }, []);
  const openTargetAccounts = useCallback(() => {
    dispatch({ type: "open-target-accounts" });
  }, []);
  const setArtifactTitleFor = useCallback((artifactId: string, title: string) => {
    dispatch({ artifactId, title, type: "rename-artifact" });
  }, []);
  const toggleArtifactMaximized = useCallback(() => {
    dispatch({ type: "toggle-maximized" });
  }, []);
  const toggleArtifactPanel = useCallback(() => {
    dispatch({ type: "toggle-panel" });
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
      openPlan,
      openGallery,
      openTargetAccounts,
      panelOpen: state.panelOpen,
      projectId: initial.projectId,
      selectInspectorElement,
      setArtifactTitleFor,
      setEditing,
      surface: state.surface,
      toggleArtifactMaximized,
      toggleArtifactPanel,
    }),
    [
      activateArtifact,
      activeArtifact,
      closeArtifact,
      initial.projectId,
      openArtifact,
      openPlan,
      openGallery,
      openTargetAccounts,
      selectInspectorElement,
      setArtifactTitleFor,
      setEditing,
      state,
      toggleArtifactMaximized,
      toggleArtifactPanel,
    ],
  );
}
