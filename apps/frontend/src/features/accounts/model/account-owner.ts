import type { WorkspaceProfile } from "./workspace-profile";
import type { AccountOwner } from "./account";

export function workspaceProfileOwner(profile: WorkspaceProfile): AccountOwner {
  return {
    id: profile.id ?? "current-workspace-user",
    name: profile.fullName.trim() || profile.displayName.trim() || "Workspace user",
    ...(profile.avatarUrl ? { avatarUrl: profile.avatarUrl } : {}),
  };
}

export function resolveAccountOwner(
  account: { owner?: AccountOwner | null; createdBy?: AccountOwner | null },
  workspaceUser: AccountOwner,
): AccountOwner {
  return account.owner ?? account.createdBy ?? workspaceUser;
}
