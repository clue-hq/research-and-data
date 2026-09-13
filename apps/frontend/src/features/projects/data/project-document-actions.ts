import { z } from "zod";
import { ClueApiError } from "@/features/accounts/data/clue-api-error";
import {
  ProjectDocumentDetailResponseSchema,
  ProjectDocumentSaveSchema,
  toProjectDocumentDetail,
  type ProjectDocument,
  type ProjectDocumentDetail,
} from "../model/project-documents";
import { projectDocumentError } from "./project-documents-error";

const ErrorDetailSchema = z.object({ code: z.string(), message: z.string().optional(), requestId: z.string().nullable().optional() });
const ErrorResponseSchema = z.union([
  z.object({ error: ErrorDetailSchema }).transform(({ error }) => error),
  z.object({ detail: ErrorDetailSchema }).transform(({ detail }) => detail),
]);

/** One save, never retried automatically: the returned ID/version becomes the next save's base. */
export async function saveProjectDocument(
  projectId: string,
  document: ProjectDocument,
  body: string,
  clueFetch: typeof fetch = fetch,
): Promise<ProjectDocumentDetail> {
  const update = ProjectDocumentSaveSchema.parse({ body, expectedRevision: document.version });
  let response: Response;
  try {
    response = await clueFetch(`/api/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(document.id)}`, {
      method: "PUT",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify(update),
    });
  } catch {
    throw projectDocumentError(502, "DOCUMENT_SAVE_FAILED", null, true);
  }
  if (!response.ok) {
    const error = ErrorResponseSchema.safeParse(await response.json().catch(() => null));
    throw projectDocumentError(
      response.status,
      error.success ? error.data.code : "HTTP_ERROR",
      (error.success ? error.data.requestId : null) ?? response.headers.get("X-Request-Id"),
      true,
    );
  }
  try {
    const result = ProjectDocumentDetailResponseSchema.parse(await response.json());
    return toProjectDocumentDetail(result.data);
  } catch {
    throw new ClueApiError("Could not confirm the save. Your changes are still here; copy them before loading the latest version.", {
      status: 502, code: "DOCUMENT_SAVE_UNCONFIRMED", requestId: response.headers.get("X-Request-Id"),
    });
  }
}
