"use client";

import { createContext, useContext } from "react";
import type { WorkspaceProfile } from "@/features/accounts/model/workspace-profile";

// The account layout resolves the workspace person on the server and injects
// it here, so no account screen ever hard-codes an owner.
const WorkspaceProfileContext = createContext<WorkspaceProfile | null>(null);

export function WorkspaceProfileProvider({ profile, children }: {
  profile: WorkspaceProfile;
  children: React.ReactNode;
}) {
  return <WorkspaceProfileContext.Provider value={profile}>{children}</WorkspaceProfileContext.Provider>;
}

export function useWorkspaceProfile() {
  return useContext(WorkspaceProfileContext);
}
