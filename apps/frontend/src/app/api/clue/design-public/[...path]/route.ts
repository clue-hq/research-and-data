import { ClueConfigurationError, lumenApiBaseUrl } from "@/auth/config";
import { handlePublicDesignProxyRequest } from "./public-proxy-handler";

/**
 * AD1.7 / founder ruling D8: the unauthenticated passthrough for the design
 * API's public, content-addressed `/asset-store/{digest}` bytes. It exists so
 * the scene editor's images load from our own origin while reaching the
 * upstream **headerlessly** — that upstream route rejects a workspace header,
 * and every workspace-gated design call keeps using the authenticated sibling
 * proxy at `../../design/[...path]/route.ts` instead.
 *
 * There is no session gate here by ruling: the upstream is public and
 * content-addressed, so this passthrough widens nothing. GET only — the
 * handler locks the path and forwards no request headers at all.
 */
type RouteContext = { params: Promise<{ path: string[] }> };

/** Mirrors the sibling's `designApiBaseUrl: enabled ? lumenApiBaseUrl() : ""`:
 * an unconfigured origin becomes the handler's 503, never a crash. */
function designApiBaseUrl(): string {
  try {
    return lumenApiBaseUrl();
  } catch (error) {
    if (error instanceof ClueConfigurationError) return "";
    throw error;
  }
}

export async function GET(request: Request, context: RouteContext) {
  const { path } = await context.params;
  return handlePublicDesignProxyRequest(request, path, {
    designApiBaseUrl: designApiBaseUrl(),
  });
}
