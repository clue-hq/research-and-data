import type { BrandKnowledgeDocument } from "../model/brand-context";
import { KnowledgeDocumentDetailSchema, toKnowledgeDocument } from "../model/brand-knowledge";

export async function saveKnowledgeDocument(
  document: BrandKnowledgeDocument, body: string, clueFetch: typeof fetch = fetch,
): Promise<BrandKnowledgeDocument> {
  if (!document.version || document.bodyLoaded === false) {
    throw new Error("This document is not available for editing.");
  }
  let response: Response;
  try {
    response = await clueFetch(`/api/clue/frontend/v1/brand-context/knowledge/documents/${encodeURIComponent(document.id)}`, {
      method: "PUT", cache: "no-store",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ body, expectedRevision: document.version }),
    });
  } catch {
    throw new Error("Could not confirm the save. Your changes are still here; please try again.");
  }
  if (!response.ok) {
    if (response.status === 409) {
      throw new Error("A newer version of this document exists. Your changes are still here; copy them before loading the latest version.");
    }
    if (response.status === 401 || response.status === 403) {
      throw new Error("You do not have permission to save this document. Your changes are still here.");
    }
    throw new Error("Could not save your changes. Please try again.");
  }
  try {
    const saved = KnowledgeDocumentDetailSchema.parse(await response.json());
    return toKnowledgeDocument(saved, document.folderId, saved.markdown);
  } catch {
    throw new Error("Could not confirm the save. Your changes are still here; please try again.");
  }
}
