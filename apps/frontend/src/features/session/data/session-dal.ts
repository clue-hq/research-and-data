import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { fetchClueAuthentication } from "@/auth/backend";
import { ClueAuthenticationError } from "@/auth/errors";
import { isAuthenticationEnabled } from "@/auth/config";
import { requireProviderSessionToken } from "@/auth/server";
import { assertLocalWorkspaceSelection, localWorkspaceInstance, workspaceCookieName } from "@/auth/local-workspace";
import {
  AuthenticatedSessionSchema,
  RequestPrincipalSchema,
  type AuthenticatedSession,
  type ProtectedSession,
  resolveWorkspaceMembership,
} from "../model/session";
import {
  protectedSessionRecoveryFor,
  type ProtectedSessionResult,
} from "../model/session-recovery";

function handleAuthenticationError(error: unknown): never {
  if (error instanceof ClueAuthenticationError) {
    if (error.status === 401) redirect("/sign-in?reason=session_expired");
    if (localWorkspaceInstance() && ["IDENTITY_NOT_PROVISIONED", "WORKSPACE_MEMBERSHIP_REQUIRED"].includes(error.code)) {
      redirect("/access-denied?code=WORKSPACE_FORBIDDEN");
    }
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
    if (error.code === "WORKSPACE_SELECTION_REQUIRED") {
      redirect("/select-workspace");
    }
  }
  throw error;
}

export async function getWorkspaceSelectionSession(): Promise<AuthenticatedSession> {
  const token = await requireProviderSessionToken();
  try {
    return AuthenticatedSessionSchema.parse(
      await fetchClueAuthentication("/auth/v1/session", { token }),
    );
  } catch (error) {
    handleAuthenticationError(error);
  }
}

export async function getProtectedSession(): Promise<ProtectedSession | null> {
  if (!isAuthenticationEnabled()) return null;
  const token = await requireProviderSessionToken();
  const cookieStore = await cookies();
  const requested = cookieStore.get(workspaceCookieName())?.value;
  try {
    return await loadProtectedSession(token, requested);
  } catch (error) {
    handleAuthenticationError(error);
  }
}

/**
 * Let protected layouts render normal infrastructure failures as page state.
 * Authentication and membership failures still redirect inside
 * `getProtectedSession`; unexpected programming errors still throw.
 */
export async function getProtectedSessionResult(): Promise<
  ProtectedSessionResult<ProtectedSession | null>
> {
  try {
    return { status: "ready", session: await getProtectedSession() };
  } catch (error) {
    const recovery = protectedSessionRecoveryFor(error);
    if (recovery) return { status: "recovery", recovery };
    throw error;
  }
}

export async function loadProtectedSession(
  token: string,
  requestedWorkspaceId: string | null | undefined,
): Promise<ProtectedSession> {
  const session = AuthenticatedSessionSchema.parse(
    await fetchClueAuthentication("/auth/v1/session", { token }),
  );
  const instance = localWorkspaceInstance();
  const membership = resolveWorkspaceMembership(session, requestedWorkspaceId, instance?.workspaceId);
  if (!membership) {
    if (instance) {
      throw new ClueAuthenticationError("No active membership in this local workspace", {
        code: "WORKSPACE_FORBIDDEN", status: 403,
      });
    }
    if (session.memberships.length > 0) {
      throw new ClueAuthenticationError(
        "An explicit workspace selection is required",
        { code: "WORKSPACE_SELECTION_REQUIRED", status: 403 },
      );
    }
    // Zero ACTIVE memberships splits two ways (review ruling FE7): a user who HAD access and
    // lost it (revoked/suspended) belongs at access-denied exactly as before this flow
    // existed; only a user with no membership history at all is the provisioning-needed
    // state routed to /onboarding/profile. The BFF re-emits either as a 403 access error.
    if (session.has_inactive_memberships) {
      throw new ClueAuthenticationError(
        "User no longer has an active Clue workspace membership",
        { code: "WORKSPACE_FORBIDDEN", status: 403 },
      );
    }
    throw new ClueAuthenticationError(
      "User has no Clue workspace membership yet",
      { code: "WORKSPACE_MEMBERSHIP_REQUIRED", status: 403 },
    );
  }
  const principal = RequestPrincipalSchema.parse(
    await fetchClueAuthentication("/auth/v1/principal", {
      token,
      workspaceId: membership.workspace_id,
    }),
  );
  if (principal.workspace_id !== membership.workspace_id) {
    throw new ClueAuthenticationError("The resolved principal does not match the selected workspace", {
      code: "WORKSPACE_FORBIDDEN", status: 403,
    });
  }
  return {
    userId: session.user_id,
    memberships: session.memberships,
    principal,
  };
}

export async function requireWorkspaceMembership(
  workspaceId: string,
): Promise<void> {
  assertLocalWorkspaceSelection(workspaceId);
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
