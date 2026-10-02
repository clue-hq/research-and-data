import { WORKSPACE_AVATAR_COLOR, type WorkspaceProfile } from "../model/workspace-profile";

/**
 * The prototype's workspace person, lifted verbatim from the design build's
 * settings fixture. Fixture research data (the Zafran activity feed) records
 * this name, so it stays the fixture's truth; the running app derives its real
 * profile from the protected session in `app/(protected)/accounts/layout.tsx`.
 */
export const workspaceProfileFixture: WorkspaceProfile = {
  fullName: "Aakash Shrivastava",
  displayName: "Aakash",
  initials: "A",
  avatarColor: WORKSPACE_AVATAR_COLOR,
};
