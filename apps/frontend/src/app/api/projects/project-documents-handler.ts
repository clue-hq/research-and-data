import { backendPath, browserResponseHeaders, hasAllowedOrigin } from "@/auth/bff";
import { clueAppOrigin, isAuthenticationEnabled } from "@/auth/config";
import { ClueAuthenticationError } from "@/auth/errors";
import { ProjectDocumentSaveSchema } from "@/features/projects/model/project-documents";

type DocumentTarget = { projectId: string; documentId?: string };
type Dependencies = {
  authenticationEnabled: () => boolean;
  appOrigin: () => string;
  requestBackend: (path: string, init: RequestInit) => Promise<Response>;
};
const defaults: Dependencies = {
  authenticationEnabled: isAuthenticationEnabled,
  appOrigin: clueAppOrigin,
  async requestBackend(path, init) {
    const { fetchAuthenticatedClueBackend } = await import("@/auth/authenticated-backend");
    return fetchAuthenticatedClueBackend(path, init);
  },
};

function errorResponse(status: number, code: string, message: string, requestId: string | null = null): Response {
  return Response.json({ error: { code, message, requestId } }, {
    status,
    headers: { "Cache-Control": "no-store", ...(requestId ? { "X-Request-Id": requestId } : {}) },
  });
}

/** Adapt the browser's save shape; session/workspace proof remains in the shared auth client. */
export async function handleProjectDocuments(
  request: Request,
  target: DocumentTarget,
  dependencies: Dependencies = defaults,
): Promise<Response> {
  try {
    if (!dependencies.authenticationEnabled()) {
      return errorResponse(503, "AUTHENTICATION_NOT_CONFIGURED", "Authentication is disabled");
    }
    if (!hasAllowedOrigin(request, dependencies.appOrigin())) {
      return errorResponse(403, "REQUEST_ORIGIN_FORBIDDEN", "Mutation origin is not allowed");
    }
    const segments = ["frontend", "v1", "projects", target.projectId, "documents"];
    if (target.documentId !== undefined) segments.push(target.documentId);
    const path = backendPath(segments);
    let body: string | undefined;
    if (request.method === "PUT") {
      let json: unknown;
      try {
        json = await request.json();
      } catch {
        return errorResponse(400, "INVALID_JSON", "A JSON document update is required");
      }
      const parsed = ProjectDocumentSaveSchema.safeParse(json);
      if (!parsed.success) {
        return errorResponse(422, "INVALID_DOCUMENT_UPDATE", "Provide a non-empty body and a positive expectedRevision");
      }
      body = JSON.stringify({ body: parsed.data.body, expected_revision: parsed.data.expectedRevision });
    }
    const upstream = await dependencies.requestBackend(path, {
      method: request.method,
      headers: { Accept: "application/json", ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
      cache: "no-store",
      body,
    });
    const headers = browserResponseHeaders(upstream.headers);
    headers.set("Cache-Control", "no-store");
    return new Response(upstream.body, { status: upstream.status, statusText: upstream.statusText, headers });
  } catch (error) {
    if (error instanceof ClueAuthenticationError) {
      return errorResponse(error.status, error.code, error.message, error.requestId);
    }
    return errorResponse(502, "PROJECT_DOCUMENTS_UNAVAILABLE", "Unable to reach project documents. Please try again.");
  }
}
