"use client";

import { createContext, useContext, useSyncExternalStore } from "react";

const DemoWorkspaceContext = createContext(false);
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
  children,
  demo,
}: {
  children: React.ReactNode;
  demo: boolean;
}) {
  return <DemoWorkspaceContext.Provider value={demo}>{children}</DemoWorkspaceContext.Provider>;
}

export function useWorkspaceSwitcher() {
  const demo = useContext(DemoWorkspaceContext);
  const selectedId = useSyncExternalStore(
    demo ? subscribe : subscribeDisabled,
    demo ? getSelection : getServerSelection,
    getServerSelection,
  );

  return {
    demo,
    workspaces: demo ? demoWorkspaces : [],
    activeWorkspace: demo
      ? demoWorkspaces.find((workspace) => workspace.id === selectedId) ?? demoWorkspaces[0]
      : null,
    selectWorkspace(id: string) {
      if (!demo || !demoWorkspaces.some((workspace) => workspace.id === id)) return;
      // This selection previews the switcher only. Tenant data and permissions
      // must be switched by the authenticated backend when it is integrated.
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
