/**
 * AD1.7 (founder ruling D8): the scene editor's image bytes come from the
 * design API's public, content-addressed `/asset-store/{digest}` route, which
 * must be reached **headerlessly** — the upstream refuses a request that
 * carries a workspace header. This is that one narrow passthrough at our own
 * origin, so the browser never leaves it (no CORS, no direct FastAPI origin).
 *
 * Everything workspace-gated (`/font-library`, `/assets/{id}/bytes`) keeps
 * using the authenticated sibling proxy at `../design/[...path]`, which stamps
 * the re-authorized `X-Workspace-Id` server-side. This handler widens nothing:
 * GET only, path locked to a 64-hex content address, zero request headers
 * forwarded, response headers allowlisted to content-type + cache-control +
 * the upstream's access-control-allow-origin (fonts are CORS-mode fetches).
 *
 * Same testable-handler shape as `api/clue/design/[...path]/design-proxy-handler.ts`.
 */
export type PublicDesignProxyDependencies = Readonly<{
  /** The design API origin; empty when LUMEN_API_BASE_URL is unconfigured. */
  designApiBaseUrl: string;
  fetchImpl?: typeof fetch;
}>;

/** The only upstream path this passthrough may reach: a content address. */
const PUBLIC_PATH = /^asset-store\/[0-9a-f]{64}$/;

/**
 * Response headers a public asset may carry back; everything else is dropped.
 * `access-control-allow-origin` rides along because the upstream route serves
 * content-addressed public bytes with `*`, and the web editor renders a page in
 * an origin-"null" sandboxed srcdoc iframe: images are no-cors and load without
 * it, but `@font-face` fetches are CORS-mode, so dropping the header made every
 * kit font silently fall back to the system stack (production, 2026-10-14).
 */
const FORWARDED_RESPONSE_HEADERS = [
  "content-type",
  "cache-control",
  "access-control-allow-origin",
] as const;

function errorResponse(
  status: number,
  code: string,
  message: string,
): Response {
  return Response.json({ error: { code, message, requestId: null } }, { status });
}

export async function handlePublicDesignProxyRequest(
  request: Request,
  path: readonly string[],
  dependencies: PublicDesignProxyDependencies,
): Promise<Response> {
  if (request.method !== "GET") return new Response(null, { status: 405 });
  const joined = path.join("/");
  if (!PUBLIC_PATH.test(joined)) return new Response(null, { status: 404 });
  if (!dependencies.designApiBaseUrl) {
    return errorResponse(
      503,
      "DESIGN_API_NOT_CONFIGURED",
      "The design API origin is not configured",
    );
  }

  const fetchImpl = dependencies.fetchImpl ?? fetch;
  // Deliberately headerless (founder ruling D8): the upstream route is
  // content-addressed, immutable, and tenant-free by design ruling R-D4-7.
  const response = await fetchImpl(
    `${dependencies.designApiBaseUrl}/${joined}`,
    { redirect: "manual" },
  );
  const headers = new Headers();
  for (const name of FORWARDED_RESPONSE_HEADERS) {
    const value = response.headers.get(name);
    if (value) headers.set(name, value);
  }
  return new Response(response.body, { status: response.status, headers });
}
