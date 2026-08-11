import "server-only";

import { cookies } from "next/headers";
import { clueApiBaseUrl } from "./config";
import { backendRequestHeaders } from "./bff";
import { ClueAuthenticationError } from "./backend";
import { providerSessionToken } from "./server";
import { loadProtectedSession } from "@/features/session/data/session-dal";
import { WORKSPACE_COOKIE } from "@/features/session/model/session";

export interface AuthenticatedBackendContext {
  requestedWorkspaceId: string | null;
  token: string;
  workspaceId: string;
}

/**
 * Resolve one provider session into the internal Clue workspace principal.
 *
 * This is shared by the browser-facing BFF and Server Component repositories:
 * both paths prove the provider session on the server and both re-authorize the
 * selected workspace through Clue Postgres before forwarding a request.
 */
export async function authenticatedBackendContext(): Promise<AuthenticatedBackendContext> {
  const token = await providerSessionToken();
  if (!token) {
    throw new ClueAuthenticationError("Sign in to continue", {
      code: "AUTHENTICATION_REQUIRED",
      status: 401,
    });
  }

  const cookieStore = await cookies();
  const requestedWorkspaceId =
    cookieStore.get(WORKSPACE_COOKIE)?.value ?? null;
  const protectedSession = await loadProtectedSession(
    token,
    requestedWorkspaceId,
  );

  return {
    requestedWorkspaceId,
    token,
    workspaceId: protectedSession.principal.workspace_id,
  };
}

function backendUrl(path: string): URL {
  if (!path.startsWith("/") || path.startsWith("//")) {
    throw new Error("Clue backend paths must be origin-relative");
  }
  return new URL(path, clueApiBaseUrl());
}

/**
 * Send one authenticated request directly from the Next server to FastAPI.
 *
 * Server Components use this instead of making a loopback request to their own
 * `/api/clue` Route Handler. Browser callers still use that same-origin BFF;
 * both paths share this exact provider-proof and workspace-header primitive.
 */
export async function fetchAuthenticatedClueBackend(
  path: string,
  init: RequestInit = {},
  context?: AuthenticatedBackendContext,
): Promise<Response> {
  const resolved = context ?? (await authenticatedBackendContext());
  return fetch(backendUrl(path), {
    ...init,
    cache: "no-store",
    headers: backendRequestHeaders(new Headers(init.headers), {
      token: resolved.token,
      workspaceId: resolved.workspaceId,
    }),
    redirect: "manual",
  });
}
