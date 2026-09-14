import {
  ProjectDocumentsResponseSchema, ProjectDocumentDetailResponseSchema,
  toProjectDocument, toProjectDocumentDetail,
} from "../model/project-documents";
import { requestProjectDocument } from "./project-document-http";
import { projectDocumentError } from "./project-documents-error";

export async function readProjectDocuments(projectId: string, signal?: AbortSignal, clueFetch: typeof fetch = fetch) {
  const response = await requestProjectDocument(projectId, null, { signal }, clueFetch);
  try { return ProjectDocumentsResponseSchema.parse(await response.json()).data.documents.map(toProjectDocument); }
  catch { throw projectDocumentError(502, "DOCUMENT_LIST_INVALID", response.headers.get("X-Request-Id")); }
}

export async function readProjectDocument(projectId: string, documentId: string, signal?: AbortSignal, clueFetch: typeof fetch = fetch) {
  const response = await requestProjectDocument(projectId, documentId, { signal }, clueFetch);
  try { return toProjectDocumentDetail(ProjectDocumentDetailResponseSchema.parse(await response.json()).data); }
  catch { throw projectDocumentError(502, "DOCUMENT_DETAIL_INVALID", response.headers.get("X-Request-Id")); }
}
