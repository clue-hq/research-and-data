import { cookies } from "next/headers";
import { ClueAuthenticationError } from "@/auth/backend";
import {
  clueApiBaseUrl,
  clueAppOrigin,
  isAuthenticationEnabled,
} from "@/auth/config";
import { providerSessionToken } from "@/auth/server";
import {
  backendPath,
  backendRequestHeaders,
  browserResponseHeaders,
  hasAllowedOrigin,
} from "@/auth/bff";
import { loadProtectedSession } from "@/features/session/data/session-dal";
import { WORKSPACE_COOKIE } from "@/features/session/model/session";

type RouteContext = { params: Promise<{ path: string[] }> };

function errorResponse(status: number, code: string, message: string) {
  return Response.json({ error: { code, message } }, { status });
}

async function proxyRequest(request: Request, context: RouteContext) {
  if (!isAuthenticationEnabled()) {
    return errorResponse(503, "AUTHENTICATION_NOT_CONFIGURED", "Authentication is disabled");
  }
  if (!hasAllowedOrigin(request, clueAppOrigin())) {
    return errorResponse(403, "REQUEST_ORIGIN_FORBIDDEN", "Mutation origin is not allowed");
  }
  const token = await providerSessionToken();
  if (!token) {
    return errorResponse(401, "AUTHENTICATION_REQUIRED", "Sign in to continue");
  }
  const { path } = await context.params;
  const cookieStore = await cookies();
  const requestedWorkspaceId = cookieStore.get(WORKSPACE_COOKIE)?.value ?? null;
  let protectedSession;
  try {
    protectedSession = await loadProtectedSession(token, requestedWorkspaceId);
  } catch (error) {
    if (error instanceof ClueAuthenticationError) {
      return errorResponse(error.status, error.code, error.message);
    }
    throw error;
  }
  const workspaceId = protectedSession.principal.workspace_id;
  if (workspaceId !== requestedWorkspaceId) {
    cookieStore.set(WORKSPACE_COOKIE, workspaceId, {
      httpOnly: true,
      sameSite: "lax",
      secure: process.env.NODE_ENV === "production",
      path: "/",
    });
  }
  const target = new URL(backendPath(path), clueApiBaseUrl());
  target.search = new URL(request.url).search;
  const method = request.method.toUpperCase();
  const body = method === "GET" || method === "HEAD" ? undefined : await request.arrayBuffer();
  const response = await fetch(target, {
    method,
    headers: backendRequestHeaders(request.headers, { token, workspaceId }),
    body,
    cache: "no-store",
    redirect: "manual",
  });
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers: browserResponseHeaders(response.headers),
  });
}

export const GET = proxyRequest;
export const POST = proxyRequest;
export const PUT = proxyRequest;
export const PATCH = proxyRequest;
export const DELETE = proxyRequest;
