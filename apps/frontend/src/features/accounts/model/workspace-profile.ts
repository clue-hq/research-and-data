/**
 * The workspace person the account screens render as "you".
 *
 * This is exactly the shape the local prototype served as
 * `SettingsWorkspace["profile"]`. The platform has no settings feature, so the
 * accounts data layer derives it from the protected session instead; the
 * feature keeps consuming one profile shape either way.
 */
export type WorkspaceProfile = {
  id?: string;
  avatarUrl?: string;
  fullName: string;
  displayName: string;
  initials: string;
  avatarColor: string;
};

/** First letters of up to two words, uppercased; never empty. */
export function workspaceInitials(name: string): string {
  const words = name.split(/[\s._-]+/).filter(Boolean).slice(0, 2);
  const letters = words.map((word) => word[0]!.toLocaleUpperCase()).join("");
  return letters || name.slice(0, 1).toLocaleUpperCase() || "?";
}

/**
 * Build the profile from a session user id.
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
