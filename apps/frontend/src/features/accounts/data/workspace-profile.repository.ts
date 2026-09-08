import type { ProtectedSession } from "@/features/session/model/session";
import {
  workspaceProfileForUserId,
  type WorkspaceProfile,
} from "../model/workspace-profile";
import { workspaceProfileFixture } from "./workspace-profile.fixture";

/**
 * Resolve the workspace person for the account screens.
 *
 * `getProtectedSession()` returns `null` when authentication is disabled (local
 * development): there is no session person to derive, so the design build's own
 * workspace profile stands in unchanged. With a session, the person is the
 * session user; the design build ships exactly one workspace avatar colour and
 * no palette to hash into, so that colour is reused rather than invented.
 */
export function getWorkspaceProfile(
  session: ProtectedSession | null,
): WorkspaceProfile {
  if (!session) return workspaceProfileFixture;
  return workspaceProfileForUserId(
    session.userId,
    workspaceProfileFixture.avatarColor,
  );
}
