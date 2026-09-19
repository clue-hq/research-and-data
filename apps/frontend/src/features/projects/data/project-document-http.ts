import { z } from "zod";
import { projectDocumentError } from "./project-documents-error";

const Detail = z.object({ code: z.string(), requestId: z.string().nullable().optional() });
const ErrorResponse = z.union([
  z.object({ error: Detail }).transform(({ error }) => error),
  z.object({ detail: Detail }).transform(({ detail }) => detail),
]);

/** Same-origin authenticated BFF; never import the server read/auth graph in a browser. */
export async function requestProjectDocument(
  projectId: string, documentId: string | null, init: RequestInit = {}, clueFetch: typeof fetch = fetch,
): Promise<Response> {
  const editing = init.method === "PUT";
  const path = `/api/projects/${encodeURIComponent(projectId)}/documents${documentId ? `/${encodeURIComponent(documentId)}` : ""}`;
  let response: Response;
  try {
    response = await clueFetch(path, { cache: "no-store", ...init });
  } catch (error) {
    if (init.signal?.aborted) throw error;
    throw projectDocumentError(502, editing ? "DOCUMENT_SAVE_FAILED" : "DOCUMENT_READ_FAILED", null, editing);
  }
  if (!response.ok) {
    const error = ErrorResponse.safeParse(await response.json().catch(() => null));
    throw projectDocumentError(response.status, error.success ? error.data.code : "HTTP_ERROR",
      (error.success ? error.data.requestId : null) ?? response.headers.get("X-Request-Id"), editing);
  }
  return response;
}
