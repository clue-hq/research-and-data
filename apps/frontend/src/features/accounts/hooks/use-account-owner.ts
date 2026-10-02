import { useWorkspaceProfile } from "@/components/shell/workspace-profile-context";
import type { AccountOwner } from "../model/account";
import { resolveAccountOwner, workspaceProfileOwner } from "../model/account-owner";
import { useMemo } from "react";

export function useAccountWorkspaceOwner() {
  const profile = useWorkspaceProfile();
  return useMemo(() => {
    if (!profile) throw new Error("Account routes require a workspace profile");
    return workspaceProfileOwner(profile);
  }, [profile]);
}

export function useAccountOwner(account: { owner?: AccountOwner | null; createdBy?: AccountOwner | null }) {
  return resolveAccountOwner(account);
}
