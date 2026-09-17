import { ClueAuthenticationError } from "@/auth/errors";
import { ClueApiError, fetchRead } from "@/features/accounts/data/frontend-api";
import {
  ProjectDocumentDetailResponseSchema,
  ProjectDocumentsResponseSchema,
  toProjectDocument,
  toProjectDocumentDetail,
  type ProjectDocument,
  type ProjectDocumentDetail,
} from "../model/project-documents";
import { projectDocumentError } from "./project-documents-error";

function documentsPath(projectId: string): string {
  return `/projects/${encodeURIComponent(projectId)}/documents`;
}

async function readDocuments(path: string, read: typeof fetchRead): Promise<unknown> {
  try {
    return await read(path);
  } catch (error) {
    if (error instanceof ClueApiError || error instanceof ClueAuthenticationError) {
      throw projectDocumentError(error.status, error.code, error.requestId);
    }
    throw projectDocumentError(502, "DOCUMENT_READ_FAILED", null);
  }
}

/** Server read through the authenticated workspace client. Empty lists are real backend results. */
export async function listProjectDocuments(projectId: string, read: typeof fetchRead = fetchRead): Promise<ProjectDocument[]> {
  const result = ProjectDocumentsResponseSchema.parse(await readDocuments(documentsPath(projectId), read));
  return result.data.documents.map(toProjectDocument);
}

export async function getProjectDocument(projectId: string, documentId: string, read: typeof fetchRead = fetchRead): Promise<ProjectDocumentDetail> {
  const result = ProjectDocumentDetailResponseSchema.parse(
    await readDocuments(`${documentsPath(projectId)}/${encodeURIComponent(documentId)}`, read),
  );
  return toProjectDocumentDetail(result.data);
}
