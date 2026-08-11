import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import {
  ClueAuthenticationError,
  fetchClueAuthentication,
} from "@/auth/backend";
import { isAuthenticationEnabled } from "@/auth/config";
import { requireProviderSessionToken } from "@/auth/server";
import {
  AuthenticatedSessionSchema,
  RequestPrincipalSchema,
  WORKSPACE_COOKIE,
  type ProtectedSession,
  resolveWorkspaceMembership,
} from "../model/session";

function handleAuthenticationError(error: unknown): never {
  if (error instanceof ClueAuthenticationError) {
    if (error.status === 401) redirect("/sign-in?reason=session_expired");
    // FI-4 slice 1 routing repair: an authenticated user who simply has no Clue footprint
    // yet (fresh Clerk identity, or identity without a workspace) belongs in onboarding —
    // the provisioning profile step — not at a dead-end access-denied page.
    if (
      error.code === "IDENTITY_NOT_PROVISIONED" ||
      error.code === "WORKSPACE_MEMBERSHIP_REQUIRED"
    ) {
      redirect("/onboarding/profile");
    }
    if (error.code === "USER_DISABLED" || error.code === "WORKSPACE_FORBIDDEN") {
      redirect(`/access-denied?code=${encodeURIComponent(error.code)}`);
    }
  }
  throw error;
}

export async function getProtectedSession(): Promise<ProtectedSession | null> {
  if (!isAuthenticationEnabled()) return null;
  const token = await requireProviderSessionToken();
  const cookieStore = await cookies();
  const requested = cookieStore.get(WORKSPACE_COOKIE)?.value;
  try {
    return await loadProtectedSession(token, requested);
  } catch (error) {
    handleAuthenticationError(error);
  }
}

export async function loadProtectedSession(
  token: string,
  requestedWorkspaceId: string | null | undefined,
): Promise<ProtectedSession> {
  const session = AuthenticatedSessionSchema.parse(
    await fetchClueAuthentication("/auth/v1/session", { token }),
  );
  const membership = resolveWorkspaceMembership(session, requestedWorkspaceId);
  if (!membership) {
    // Zero memberships is the provisioning-needed state, distinct from WORKSPACE_FORBIDDEN
    // (which means a selected workspace refused an existing member). Pages route this to
    // /onboarding/profile; the BFF re-emits it as a 403 access error.
    throw new ClueAuthenticationError(
      "User has no active Clue workspace membership",
      { code: "WORKSPACE_MEMBERSHIP_REQUIRED", status: 403 },
    );
  }
  const principal = RequestPrincipalSchema.parse(
    await fetchClueAuthentication("/auth/v1/principal", {
      token,
      workspaceId: membership.workspace_id,
    }),
  );
  return {
    userId: session.user_id,
    memberships: session.memberships,
    principal,
  };
}

export async function requireWorkspaceMembership(
  workspaceId: string,
): Promise<void> {
  const token = await requireProviderSessionToken();
  try {
    RequestPrincipalSchema.parse(
      await fetchClueAuthentication("/auth/v1/principal", {
        token,
        workspaceId,
      }),
    );
  } catch (error) {
    handleAuthenticationError(error);
  }
}
