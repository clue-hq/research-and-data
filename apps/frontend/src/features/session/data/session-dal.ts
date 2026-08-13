import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { fetchClueAuthentication } from "@/auth/backend";
import { ClueAuthenticationError } from "@/auth/errors";
import { isAuthenticationEnabled } from "@/auth/config";
import { requireProviderSessionToken } from "@/auth/server";
import {
  AuthenticatedSessionSchema,
  RequestPrincipalSchema,
  WORKSPACE_COOKIE,
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
    if (
      error.code === "IDENTITY_NOT_PROVISIONED" ||
      error.code === "USER_DISABLED" ||
      error.code === "WORKSPACE_FORBIDDEN"
    ) {
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
  const requested = cookieStore.get(WORKSPACE_COOKIE)?.value;
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
  const membership = resolveWorkspaceMembership(session, requestedWorkspaceId);
  if (!membership) {
    if (session.memberships.length > 0) {
      throw new ClueAuthenticationError(
        "An explicit workspace selection is required",
        { code: "WORKSPACE_SELECTION_REQUIRED", status: 403 },
      );
    }
    throw new ClueAuthenticationError(
      "User has no active Clue workspace membership",
      { code: "WORKSPACE_FORBIDDEN", status: 403 },
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
