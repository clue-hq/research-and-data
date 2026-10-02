"use client";

import { createContext, useContext, type ReactNode } from "react";

type LocalWorkspaceLabel = Readonly<{ name: string; port: string }>;
const LocalWorkspaceContext = createContext<LocalWorkspaceLabel | null>(null);

export function LocalWorkspaceProvider({ value, children }: {
  value: LocalWorkspaceLabel | null;
  children: ReactNode;
}) {
  return <LocalWorkspaceContext.Provider value={value}>{children}</LocalWorkspaceContext.Provider>;
}

export function useLocalWorkspaceLabel(): LocalWorkspaceLabel | null {
  return useContext(LocalWorkspaceContext);
}
