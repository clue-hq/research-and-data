import { ClueAuthenticationError } from "@/auth/errors";
import { backendPath, browserResponseHeaders } from "@/auth/bff";
import { streamingFetchOptions } from "@/auth/streaming-dispatcher";

/**
 * The design API speaks workspace-header auth only (`X-Workspace-Id`) and must
 * never face browsers directly. This handler is the one crossing point: the
 * route binding proves the platform session and re-authorizes the workspace
 * through Clue Postgres (authenticatedBackendContext), and only that resolved
 * workspace id is stamped — browser-supplied credentials and workspace
 * headers are never forwarded. Same testable-handler shape as
 * `api/onboarding/provision/provision-handler.ts`.
 */
export type DesignProxyDependencies = Readonly<{
  authenticationEnabled: boolean;
  originAllowed: boolean;
  /** Resolves the session's re-authorized workspace id; throws ClueAuthenticationError. */
  workspaceId(): Promise<string>;
  designApiBaseUrl: string;
  fetchImpl?: typeof fetch;
}>;

/** Request headers a design call may carry across; everything else is dropped. */
const FORWARDED_REQUEST_HEADERS = [
  "accept",
  "content-type",
  "idempotency-key",
  // Lets an image the browser already holds come back as a bodiless 304.
  "if-none-match",
  "last-event-id",
] as const;

/** Statuses a Response must be built without a body for. */
const NULL_BODY_STATUSES = new Set([101, 204, 205, 304]);

function errorResponse(
  status: number,
  code: string,
  message: string,
  requestId: string | null = null,
): Response {
  return Response.json(
    { error: { code, message, requestId } },
    {
      status,
      headers: requestId ? { "X-Request-Id": requestId } : undefined,
    },
  );
}

export async function handleDesignProxyRequest(
  request: Request,
  path: readonly string[],
  dependencies: DesignProxyDependencies,
): Promise<Response> {
  if (!dependencies.authenticationEnabled) {
    return errorResponse(
      503,
      "AUTHENTICATION_NOT_CONFIGURED",
      "Authentication is disabled",
    );
  }
  if (!dependencies.originAllowed) {
    return errorResponse(
      403,
      "REQUEST_ORIGIN_FORBIDDEN",
      "Mutation origin is not allowed",
    );
  }

  let workspaceId: string;
  try {
    workspaceId = await dependencies.workspaceId();
  } catch (error) {
    if (error instanceof ClueAuthenticationError) {
      return errorResponse(error.status, error.code, error.message, error.requestId);
    }
    throw error;
  }

  // A background upload selected in one workspace must never follow a changed cookie.
  // This is a precondition only: it cannot select or authorize a workspace.
  const expectedWorkspace = request.headers.get("X-Expected-Workspace-Id");
  if (expectedWorkspace && expectedWorkspace !== workspaceId) {
    return errorResponse(409, "WORKSPACE_CHANGED", "Workspace changed. Return to the original workspace to retry this upload.");
  }

  const outgoing = new Headers({ "X-Workspace-Id": workspaceId });
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) outgoing.set(name, value);
  }

  const method = request.method.toUpperCase();
  const body =
    method === "GET" || method === "HEAD"
      ? undefined
      : await request.arrayBuffer();
  const search = new URL(request.url).search;
  const fetchImpl = dependencies.fetchImpl ?? fetch;
  const response = await fetchImpl(
    `${dependencies.designApiBaseUrl}${backendPath(path)}${search}`,
    {
      method,
      headers: outgoing,
      body,
      cache: "no-store",
      redirect: "manual",
      // `last-event-id` is forwarded above, so this handler is built to proxy
      // the design run-event stream. An event stream must not run under
      // undici's 300s body timeout; see `streaming-dispatcher.ts`. A no-op for
      // ordinary request/response calls, and for an injected `fetchImpl` that
      // ignores the option.
      ...streamingFetchOptions(outgoing),
    },
  );
  return new Response(NULL_BODY_STATUSES.has(response.status) ? null : response.body, {
    status: response.status,
    statusText: response.statusText,
    headers: browserResponseHeaders(response.headers),
  });
}
