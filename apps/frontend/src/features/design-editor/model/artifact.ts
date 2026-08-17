import { z } from "zod";

/**
 * W1.3: the artifact→design-document read seam, frontend shape.
 *
 * `ChatShellArtifact` is the contract-doc shape the editor shell consumes
 * ({id, projectId, kind, title, currentVersionId, status, capabilities}) plus
 * `documentId` — the seam's entire point: today `documentId === id` (design
 * documents are not yet registered as platform artifacts; the backend's v1
 * resolver is the identity mapping), and when the real linkage lands only the
 * backend changes — every consumer already reads `documentId`.
 */
export const ChatShellArtifactSchema = z.object({
  id: z.string().min(1),
  projectId: z.string().min(1),
  documentId: z.string().min(1),
  kind: z.enum(["web", "ad"]),
  title: z.string().min(1),
  currentVersionId: z.string().min(1),
  status: z.string().min(1),
  capabilities: z.record(z.string(), z.boolean()).default({}),
});

export type ChatShellArtifact = z.infer<typeof ChatShellArtifactSchema>;

/** The backend wire (snake_case envelope) → `ChatShellArtifact`. */
export const DesignArtifactWireSchema = z
  .object({
    data: z.object({
      id: z.string().min(1),
      project_id: z.string().min(1),
      document_id: z.string().min(1),
      kind: z.enum(["web", "ad"]),
      title: z.string().min(1),
      status: z.string().min(1),
      current_version_id: z.string().min(1),
    }),
  })
  .transform(({ data }) =>
    ChatShellArtifactSchema.parse({
      id: data.id,
      projectId: data.project_id,
      documentId: data.document_id,
      kind: data.kind,
      title: data.title,
      currentVersionId: data.current_version_id,
      status: data.status,
    }),
  );
