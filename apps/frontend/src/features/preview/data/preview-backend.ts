import { createHash, randomUUID } from "node:crypto";
import { z } from "zod";
import { attachmentLimitError, attachmentMediaType } from "@/features/projects/model/chat-attachments";
import { ProjectDocumentSaveSchema, ProjectDocumentSummarySchema } from "@/features/projects/model/project-documents";
import { previewDocuments, previewMembers, previewPages, previewProfile, previewResearchFields, previewWorkspace } from "./preview.fixture";
import { isFrontendPreviewMode } from "./preview-mode";

const ProfileEdit = z.strictObject({
  full_name: z.string().trim().min(1).max(200).optional(),
  display_name: z.string().trim().max(200).nullable().optional(),
});
const json = (data: unknown, status = 200) => Response.json(data, { status, headers: { "Cache-Control": "no-store" } });
const error = (status: number, code: string, message: string) => json({ error: { code, message, requestId: null } }, status);

function createPreviewState() {
  return { profile: structuredClone(previewProfile), documents: new Map<string, ReturnType<typeof previewDocuments>>() };
}

/** No network/storage dependencies. State lasts for one local dev-server process. */
export function createPreviewBackend(state = createPreviewState()) {
  const { documents } = state;
  return async (path: string, init: RequestInit = {}): Promise<Response> => {
    const url = new URL(path, "http://preview.invalid");
    const method = init.method ?? "GET";
    if (method === "GET") {
      if (/^\/frontend\/v1\/projects\/[^/]+\/(discovery\/current|research\/progress)$/.test(url.pathname)) return json({ data: null });
      if (/^\/frontend\/v1\/projects\/[^/]+\/product-notices$/.test(url.pathname)) return json({ notices: [] });
      switch (url.pathname) {
        case "/frontend/v1/settings/profile": return json(state.profile);
        case "/frontend/v1/settings/workspace": return json(previewWorkspace);
        case "/frontend/v1/settings/members": return json(previewMembers);
        case "/frontend/v1/settings/pages": return json(previewPages);
        case "/frontend/v1/settings/research-fields": {
          const entity = url.searchParams.get("entity");
          if (entity !== "accounts" && entity !== "contacts") return error(422, "INVALID_ENTITY", "Choose Accounts or Contacts.");
          return json(previewResearchFields(entity));
        }
      }
    }
    if (method === "PATCH" && url.pathname === "/frontend/v1/settings/profile") {
      const parsed = ProfileEdit.safeParse(await new Request(url, init).json().catch(() => null));
      if (!parsed.success) return error(422, "INVALID_PROFILE", "Provide a valid profile name.");
      state.profile = { ...state.profile, ...parsed.data };
      return json(state.profile);
    }
    const documentRoute = /^\/frontend\/v1\/projects\/([^/]+)\/documents(?:\/([^/]+))?$/.exec(url.pathname);
    if (documentRoute) {
      const projectId = decodeURIComponent(documentRoute[1]);
      const documentId = documentRoute[2] && decodeURIComponent(documentRoute[2]);
      if (!documents.has(projectId)) documents.set(projectId, previewDocuments(projectId));
      const records = documents.get(projectId)!;
      if (!documentId && method === "GET") return json({ data: { documents: records.map((record) => ProjectDocumentSummarySchema.parse(record)) } });
      const record = records.find((item) => item.id === documentId);
      if (!record) return error(404, "DOCUMENT_NOT_FOUND", "This demo document does not exist.");
      if (method === "GET") return json({ data: record });
      if (method === "PUT") {
        const body = await new Request(url, init).json().catch(() => null);
        const parsed = ProjectDocumentSaveSchema.safeParse({ body: body?.body, expectedRevision: body?.expected_revision });
        if (!parsed.success) return error(422, "INVALID_DOCUMENT_UPDATE", "Provide document text and its version.");
        if (parsed.data.expectedRevision !== record.version) return error(409, "DOCUMENT_REVISION_CONFLICT", "Reload this document before saving again.");
        record.markdown = parsed.data.body;
        record.version += 1;
        record.updated_at = new Date().toISOString();
        return json({ data: record });
      }
    }
    if (url.pathname === "/frontend/v1/uploads" && method === "POST") {
      const form = await new Request(url, init).formData().catch(() => null);
      const file = form?.get("file");
      if (!(file instanceof File)) return error(422, "FILE_REQUIRED", "Choose a file to attach.");
      const mediaType = attachmentMediaType(file);
      if (!mediaType) return error(415, "UPLOAD_UNSUPPORTED_TYPE", "This file type is not supported.");
      const limit = attachmentLimitError([], [file]);
      if (limit) return error(413, "UPLOAD_TOO_LARGE", limit);
      const uploadId = `preview-${randomUUID()}`;
      return json({ data: {
        upload_id: uploadId, artifact_key: `preview/${uploadId}/${file.name}`, filename: file.name,
        byte_count: file.size, media_type: mediaType,
        sha256: createHash("sha256").update(Buffer.from(await file.arrayBuffer())).digest("hex"),
      } });
    }
    return error(501, "PREVIEW_ACTION_UNAVAILABLE", "This action requires a connected workspace. The local preview does not send, publish or run agents.");
  };
}

type PreviewGlobal = typeof globalThis & { __clueFrontendPreviewState?: ReturnType<typeof createPreviewState> };
/** Shared across Next's server bundles, but deliberately never persisted or sent upstream. */
export async function requestPreviewBackend(path: string, init?: RequestInit) {
  if (!isFrontendPreviewMode()) throw new Error("Frontend preview is not enabled.");
  const scope = globalThis as PreviewGlobal;
  // Keep records, not the handler closure, across HMR so code edits take effect.
  scope.__clueFrontendPreviewState ??= createPreviewState();
  return createPreviewBackend(scope.__clueFrontendPreviewState)(path, init);
}
