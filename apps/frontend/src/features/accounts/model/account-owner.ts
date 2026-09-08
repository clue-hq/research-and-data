import type { WorkspaceProfile } from "./workspace-profile";
import type { AccountOwner } from "./account";

/** What the screens print when an account has neither an owner nor a creator (ruling R6). */
export const UNASSIGNED_OWNER_LABEL = "Unassigned";

export function workspaceProfileOwner(profile: WorkspaceProfile): AccountOwner {
  return {
    id: profile.id ?? "current-workspace-user",
    name: profile.fullName.trim() || profile.displayName.trim() || "Workspace user",
    ...(profile.avatarUrl ? { avatarUrl: profile.avatarUrl } : {}),
  };
}

/**
 * The person an account belongs to: the assigned owner, else the recorded
 * creator, else nobody.
 *
 * `owner` and `createdBy` are workspace users the backend serves (contract v1,
 * ruling R6). The viewer is NOT a candidate — an unowned account read by Priya
 * used to render as Priya's, which is a fabricated fact about a CRM row.
 */
export function resolveAccountOwner(
  account: { owner?: AccountOwner | null; createdBy?: AccountOwner | null },
): AccountOwner | null {
  return account.owner ?? account.createdBy ?? null;
}
