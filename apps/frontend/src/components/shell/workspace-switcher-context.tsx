"use client";

import { createContext, startTransition, useContext, useSyncExternalStore } from "react";

export type SwitcherWorkspace = {
  id: string;
  name: string;
  initials: string;
  role: string;
  /** The company's logo; the initials stand in when there is none. */
  logoUrl?: string | null;
};

type SwitcherValue = {
  demo: boolean;
  workspaces: readonly SwitcherWorkspace[];
  activeWorkspaceId: string | null;
  onSelect: ((workspaceId: string) => void) | null;
};

const WorkspaceSwitcherContext = createContext<SwitcherValue>({
  demo: false,
  workspaces: [],
  activeWorkspaceId: null,
  onSelect: null,
});
const storageKey = "clue:demo-workspace:v1";
const changeEvent = "clue:demo-workspace-change";
const demoWorkspaces = [
  { id: "clue", name: "Clue workspace", initials: "C", role: "Admin" },
  { id: "acme", name: "Acme", initials: "A", role: "Admin" },
  { id: "brightside", name: "Brightside", initials: "B", role: "Member" },
];
let transientSelection: string | null = null;

function getSelection() {
  if (transientSelection) return transientSelection;
  try {
    const stored = localStorage.getItem(storageKey);
    return stored && demoWorkspaces.some((workspace) => workspace.id === stored)
      ? stored
      : "clue";
  } catch {
    return "clue";
  }
}

function subscribe(onChange: () => void) {
  function onStorage(event: StorageEvent) {
    if (event.key === storageKey || event.key === null) onChange();
  }
  window.addEventListener("storage", onStorage);
  window.addEventListener(changeEvent, onChange);
  return () => {
    window.removeEventListener("storage", onStorage);
    window.removeEventListener(changeEvent, onChange);
  };
}

function getServerSelection() {
  return "clue";
}

function subscribeDisabled() {
  return () => {};
}

export function WorkspaceSwitcherProvider({
  activeWorkspaceId = null,
  children,
  demo,
  onSelect = null,
  workspaces = [],
}: {
  activeWorkspaceId?: string | null;
  children: React.ReactNode;
  demo: boolean;
  onSelect?: ((workspaceId: string) => void) | null;
  workspaces?: readonly SwitcherWorkspace[];
}) {
  return (
    <WorkspaceSwitcherContext.Provider
      value={{ activeWorkspaceId, demo, onSelect, workspaces }}
    >
      {children}
    </WorkspaceSwitcherContext.Provider>
  );
}

export function useWorkspaceSwitcher(): {
  demo: boolean;
  workspaces: readonly SwitcherWorkspace[];
  activeWorkspace: SwitcherWorkspace | null;
  selectWorkspace: (id: string) => void;
} {
  const { activeWorkspaceId, demo, onSelect, workspaces } = useContext(
    WorkspaceSwitcherContext,
  );
  const selectedId = useSyncExternalStore(
    demo ? subscribe : subscribeDisabled,
    demo ? getSelection : getServerSelection,
    getServerSelection,
  );

  if (demo) {
    return {
      demo,
      workspaces: demoWorkspaces,
      activeWorkspace:
        demoWorkspaces.find((workspace) => workspace.id === selectedId)
        ?? demoWorkspaces[0]
        ?? null,
      selectWorkspace(id: string) {
        if (!demoWorkspaces.some((workspace) => workspace.id === id)) return;
        // This selection previews the switcher only: the demo build has no tenant
        // behind it, so the choice lives in browser storage and nowhere else.
        try {
          localStorage.setItem(storageKey, id);
          transientSelection = null;
        } catch {
          // Keep the preview usable when browser storage is unavailable.
          transientSelection = id;
        }
        window.dispatchEvent(new Event(changeEvent));
      },
    };
  }

  // Live mode: the memberships of the signed-in user, switched on the server.
  // Nothing is written to the browser — the workspace cookie is the only record
  // of the choice, and only the server may set it.
  return {
    demo,
    workspaces,
    activeWorkspace:
      workspaces.find((workspace) => workspace.id === activeWorkspaceId) ?? null,
    selectWorkspace(id: string) {
      if (!onSelect) return;
      if (id === activeWorkspaceId) return;
      if (!workspaces.some((workspace) => workspace.id === id)) return;
      startTransition(() => onSelect(id));
    },
  };
}
