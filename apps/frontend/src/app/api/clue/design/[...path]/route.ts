import { cookies } from "next/headers";
import { clueAppOrigin, isAuthenticationEnabled, lumenApiBaseUrl } from "@/auth/config";
import { hasAllowedOrigin } from "@/auth/bff";
import { authenticatedBackendContext } from "@/auth/authenticated-backend";
import { workspaceCookieName } from "@/auth/local-workspace";
import { handleDesignProxyRequest } from "./design-proxy-handler";

/**
 * W1.2: the authenticated BFF for the design API (LUMEN_API_BASE_URL,
 * server-side only). Mirrors the platform proxy at `../..//[...path]/route.ts`
 * — same guards, same error envelope, same workspace-cookie repair — but
 * forwards with the design API's `X-Workspace-Id` header instead of a bearer:
 * the session is proven and the workspace re-authorized here, because the
 * design API trusts its workspace header blindly by contract.
 */
type RouteContext = { params: Promise<{ path: string[] }> };

async function proxyRequest(request: Request, context: RouteContext) {
  const authenticationEnabled = isAuthenticationEnabled();
  const { path } = await context.params;
  return handleDesignProxyRequest(request, path, {
    authenticationEnabled,
    originAllowed:
      authenticationEnabled && hasAllowedOrigin(request, clueAppOrigin()),
    designApiBaseUrl: authenticationEnabled ? lumenApiBaseUrl() : "",
    async workspaceId() {
      const backendContext = await authenticatedBackendContext();
      if (backendContext.workspaceId !== backendContext.requestedWorkspaceId) {
        const cookieStore = await cookies();
        cookieStore.set(workspaceCookieName(), backendContext.workspaceId, {
          httpOnly: true,
          sameSite: "lax",
          secure: process.env.NODE_ENV === "production",
          path: "/",
        });
      }
      return backendContext.workspaceId;
    },
  });
}

export const GET = proxyRequest;
export const POST = proxyRequest;
export const PUT = proxyRequest;
export const PATCH = proxyRequest;
export const DELETE = proxyRequest;
