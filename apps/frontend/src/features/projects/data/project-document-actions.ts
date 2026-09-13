import { ClueApiError } from "@/features/accounts/data/clue-api-error";
import {
  ProjectDocumentDetailResponseSchema,
  ProjectDocumentSaveSchema,
  toProjectDocumentDetail,
  type ProjectDocument,
  type ProjectDocumentDetail,
} from "../model/project-documents";
import { requestProjectDocument } from "./project-document-http";

/** One save, never retried automatically: the returned ID/version becomes the next save's base. */
export async function saveProjectDocument(
  projectId: string,
  document: ProjectDocument,
  body: string,
  clueFetch: typeof fetch = fetch,
): Promise<ProjectDocumentDetail> {
  const update = ProjectDocumentSaveSchema.parse({ body, expectedRevision: document.version });
  const response = await requestProjectDocument(projectId, document.id, {
    method: "PUT", headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(update),
  }, clueFetch);
  try {
    const result = ProjectDocumentDetailResponseSchema.parse(await response.json());
    return toProjectDocumentDetail(result.data);
  } catch {
    throw new ClueApiError("Could not confirm the save. Your changes are still here; copy them before loading the latest version.", {
      status: 502, code: "DOCUMENT_SAVE_UNCONFIRMED", requestId: response.headers.get("X-Request-Id"),
    });
  }
}
