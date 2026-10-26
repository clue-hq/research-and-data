"use client";
import { createContext, useContext, useMemo, type ReactNode } from "react";
import { createWorkspaceRepository, type WorkspaceRepository } from "./workspace.repository";
const Context = createContext<WorkspaceRepository | null>(null);
export function OrchestrationProvider({ enabled, children }: { enabled: boolean; children: ReactNode }) {
  const repository = useMemo(() => enabled ? createWorkspaceRepository() : null, [enabled]);
  return <Context.Provider value={repository}>{children}</Context.Provider>;
}
export function useWorkspaceRepository() { return useContext(Context); }
