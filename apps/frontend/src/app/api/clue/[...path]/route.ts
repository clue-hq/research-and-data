import { cookies } from "next/headers";
import { ClueAuthenticationError } from "@/auth/errors";
import { clueAppOrigin, isAuthenticationEnabled } from "@/auth/config";
import {
  backendPath,
  browserResponseHeaders,
  hasAllowedOrigin,
} from "@/auth/bff";
import {
  authenticatedBackendContext,
  fetchAuthenticatedClueBackend,
} from "@/auth/authenticated-backend";
import { localProvisioningRefusal, workspaceCookieName } from "@/auth/local-workspace";
import { PAGE_WORKSPACE_HEADER } from "@/features/projects/data/chat-api";

type RouteContext = { params: Promise<{ path: string[] }> };

function errorResponse(
  status: number,
  code: string,
  message: string,
  requestId: string | null = null,
) {
  return Response.json(
    { error: { code, message, requestId } },
    {
      status,
      headers: requestId ? { "X-Request-Id": requestId } : undefined,
    },
  );
}

async function proxyRequest(request: Request, context: RouteContext) {
  if (!isAuthenticationEnabled()) {
    return errorResponse(503, "AUTHENTICATION_NOT_CONFIGURED", "Authentication is disabled");
  }
  if (!hasAllowedOrigin(request, clueAppOrigin())) {
    return errorResponse(403, "REQUEST_ORIGIN_FORBIDDEN", "Mutation origin is not allowed");
  }
  const { path } = await context.params;
  if (path.join("/") === "auth/v1/provision") {
    const refusal = localProvisioningRefusal();
    if (refusal) return refusal;
  }
  let backendContext;
  try {
    backendContext = await authenticatedBackendContext();
  } catch (error) {
    if (error instanceof ClueAuthenticationError) {
      return errorResponse(
        error.status,
        error.code,
        error.message,
        error.requestId,
      );
    }
    throw error;
  }
  // A page names the workspace it was loaded for. When the selected workspace has changed since
  // (a switch in another tab, or one that landed after the page loaded), its data would come from
  // the new workspace while the page still shows the old one: refuse, and the page reloads (L4-4).
  const pageWorkspace = request.headers.get(PAGE_WORKSPACE_HEADER);
  if (pageWorkspace && pageWorkspace !== backendContext.workspaceId) {
    return errorResponse(
      409,
      "WORKSPACE_CHANGED",
      "The selected workspace changed since this page was loaded.",
    );
  }
  if (backendContext.workspaceId !== backendContext.requestedWorkspaceId) {
    const cookieStore = await cookies();
    cookieStore.set(workspaceCookieName(), backendContext.workspaceId, {
      httpOnly: true,
      sameSite: "lax",
      secure: process.env.NODE_ENV === "production",
      path: "/",
    });
  }
  const method = request.method.toUpperCase();
  const body =
    method === "GET" || method === "HEAD"
      ? undefined
      : await request.arrayBuffer();
  const search = new URL(request.url).search;
  const response = await fetchAuthenticatedClueBackend(
    `${backendPath(path)}${search}`,
    {
      method,
      headers: request.headers,
      body,
    },
    backendContext,
  );
  // A 304 (an ETag revalidation) must be built without a body.
  const nullBody = [101, 204, 205, 304].includes(response.status);
  return new Response(nullBody ? null : response.body, {
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
