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
} from "../model/session";

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
  }
  throw error;
}

export async function getProtectedSession(): Promise<ProtectedSession | null> {
  if (!isAuthenticationEnabled()) return null;
  const token = await requireProviderSessionToken();
  try {
    const session = AuthenticatedSessionSchema.parse(
      await fetchClueAuthentication("/auth/v1/session", { token }),
    );
    if (session.memberships.length === 0) {
      redirect("/access-denied?code=IDENTITY_NOT_PROVISIONED");
    }
    const cookieStore = await cookies();
    const requested = cookieStore.get(WORKSPACE_COOKIE)?.value;
    const membership =
      session.memberships.find((item) => item.workspace_id === requested) ??
      session.memberships[0];
    if (!membership) redirect("/access-denied?code=WORKSPACE_FORBIDDEN");
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
  } catch (error) {
    handleAuthenticationError(error);
  }
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
