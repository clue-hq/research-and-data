import "server-only";

import { cookies } from "next/headers";
import { clueApiBaseUrl, lumenApiBaseUrl } from "./config";
import { backendRequestHeaders } from "./bff";
import { ClueAuthenticationError } from "./errors";
import { providerSessionToken } from "./server";
import { streamingFetchOptions } from "./streaming-dispatcher";
import { loadProtectedSession } from "@/features/session/data/session-dal";
import { workspaceCookieName } from "./local-workspace";

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
    cookieStore.get(workspaceCookieName())?.value ?? null;
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
 * Send one authenticated request from the Next server to the DESIGN API.
 *
 * The design sibling of `fetchAuthenticatedClueBackend`, and the server-side
 * half of the same seam the browser-facing proxy owns
 * (`app/api/clue/design/[...path]`): the provider session is proven here and
 * the workspace re-authorized through Clue Postgres, and only that resolved
 * workspace id is stamped — the design API trusts `X-Workspace-Id` blindly by
 * contract, so it must never face a browser and must never be handed a
 * browser-supplied workspace.
 *
 * Pass a resolved `context` when several calls share one page render;
 * otherwise every call re-proves the session against the platform API.
 */
export async function fetchAuthenticatedDesignBackend(
  path: string,
  init: RequestInit = {},
  context?: AuthenticatedBackendContext,
): Promise<Response> {
  if (!path.startsWith("/") || path.startsWith("//")) {
    throw new Error("Design backend paths must be origin-relative");
  }
  const resolved = context ?? (await authenticatedBackendContext());
  const headers = new Headers(init.headers);
  headers.set("X-Workspace-Id", resolved.workspaceId);
  return fetch(new URL(path, lumenApiBaseUrl()), {
    ...init,
    // An event stream must not run under undici's 300s body timeout; see
    // `streaming-dispatcher.ts`. A no-op for ordinary request/response calls.
    ...streamingFetchOptions(headers),
    cache: "no-store",
    headers,
    redirect: "manual",
  });
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
  const headers = backendRequestHeaders(new Headers(init.headers), {
    token: resolved.token,
    workspaceId: resolved.workspaceId,
  });
  return fetch(backendUrl(path), {
    ...init,
    // An event stream must not run under undici's 300s body timeout; see
    // `streaming-dispatcher.ts`. A no-op for ordinary request/response calls.
    ...streamingFetchOptions(headers),
    cache: "no-store",
    headers,
    redirect: "manual",
  });
}
