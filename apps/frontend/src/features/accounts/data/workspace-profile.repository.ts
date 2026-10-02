import type { ProtectedSession } from "@/features/session/model/session";
import {
  workspaceProfileForUserId,
  type WorkspaceProfile,
} from "../model/workspace-profile";
import { workspaceProfileFixture } from "./workspace-profile.fixture";
import { accountsFixtureMode } from "./repository-mode";

/**
 * The neutral person shown when nobody is signed in on a live deployment.
 *
 * Naming a person here would be a fabricated fact about the workspace, so the
 * profile stays deliberately anonymous; it reuses the design build's single
 * avatar colour because no palette exists to hash into.
 */
const anonymousWorkspaceProfile: WorkspaceProfile = {
  fullName: "Workspace",
  displayName: "Workspace",
  initials: "W",
  avatarColor: workspaceProfileFixture.avatarColor,
};

/**
 * Resolve the workspace person for the account screens.
 *
 * `getProtectedSession()` returns `null` when authentication is disabled: in
 * fixture mode that is the design build, so its own workspace profile stands
 * in (the Zafran activity feed records that name). On the live path a missing
 * session must NOT leak a fixture person, so the neutral profile is used
 * instead. With a session, the person is the session user; the design build
 * ships exactly one workspace avatar colour and no palette to hash into, so
 * that colour is reused rather than invented.
 */
export function getWorkspaceProfile(
  session: ProtectedSession | null,
): WorkspaceProfile {
  if (!session) {
    return accountsFixtureMode()
      ? workspaceProfileFixture
      : anonymousWorkspaceProfile;
  }
  return workspaceProfileForUserId(
    session.userId,
    workspaceProfileFixture.avatarColor,
  );
}
