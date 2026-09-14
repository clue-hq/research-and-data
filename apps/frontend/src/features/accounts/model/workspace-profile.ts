/** Shared shell person shape. Live routes resolve it from Settings profile/workspace reads. */
export type WorkspaceProfile = {
  workspaceName?: string;
  id?: string;
  avatarUrl?: string;
  fullName: string;
  displayName: string;
  initials: string;
  avatarColor: string;
};

/** The design build supplies one fixed avatar colour. */
export const WORKSPACE_AVATAR_COLOR = "#8343A5";

/** First letters of up to two words, uppercased; never empty. */
export function workspaceInitials(name: string): string {
  const words = name.split(/[\s._-]+/).filter(Boolean).slice(0, 2);
  const letters = words.map((word) => word[0]!.toLocaleUpperCase()).join("");
  return letters || name.slice(0, 1).toLocaleUpperCase() || "?";
}

/**
 * Legacy adapter retained for callers outside the authenticated Settings path.
 *
 * The session contract (`features/session/model/session.ts`) carries no display
 * name and no email: `user_id`, memberships, and the request principal are all
 * it holds. So the name IS the user id — its local part when the identity
 * provider issues an email-shaped id — and nothing is invented around it.
 */
export function workspaceProfileForUserId(
  userId: string,
  avatarColor: string,
): WorkspaceProfile {
  const name = userId.includes("@")
    ? userId.slice(0, userId.indexOf("@"))
    : userId;
  return {
    id: userId,
    fullName: name,
    displayName: name,
    initials: workspaceInitials(name),
    avatarColor,
  };
}
