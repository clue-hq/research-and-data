import { cookies } from "next/headers";
import { auth } from "@clerk/nextjs/server";
import { clueApiBaseUrl, isAuthenticationEnabled } from "@/auth/config";
import {
  backendPath,
  backendRequestHeaders,
  browserResponseHeaders,
  hasAllowedOrigin,
} from "@/auth/bff";
import { WORKSPACE_COOKIE } from "@/features/session/model/session";

type RouteContext = { params: Promise<{ path: string[] }> };

function errorResponse(status: number, code: string, message: string) {
  return Response.json({ error: { code, message } }, { status });
}

async function proxyRequest(request: Request, context: RouteContext) {
  if (!isAuthenticationEnabled()) {
    return errorResponse(503, "AUTHENTICATION_NOT_CONFIGURED", "Authentication is disabled");
  }
  if (!hasAllowedOrigin(request)) {
    return errorResponse(403, "REQUEST_ORIGIN_FORBIDDEN", "Mutation origin is not allowed");
  }
  const session = await auth({ acceptsToken: "session_token" });
  if (!session.isAuthenticated) {
    return errorResponse(401, "AUTHENTICATION_REQUIRED", "Sign in to continue");
  }
  const token = await session.getToken();
  if (!token) {
    return errorResponse(401, "SESSION_INVALID", "The session has expired");
  }
  const { path } = await context.params;
  const cookieStore = await cookies();
  const workspaceId = cookieStore.get(WORKSPACE_COOKIE)?.value ?? null;
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
