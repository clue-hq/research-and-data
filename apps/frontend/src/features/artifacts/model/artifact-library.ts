import { z } from "zod";
import { collateralTypeFor, editedLabelFor, sizeFor } from "@/features/design-editor/adapter/gallery";
import { DesignDocumentKindSchema, type DesignDocumentKind } from "@/features/design-editor/model/artifact";
import {
  ProjectArtifactSchema,
  type ProjectArtifact,
} from "@/features/projects/model/project-workspace";

/** `GET /frontend/v1/artifacts` row, as the backend serializes it (snake_case, offsets allowed). */
export const ArtifactWireSchema = z.object({
  id: z.string().min(1),
  document_id: z.string().min(1),
  project_id: z.string().min(1),
  project_title: z.string().min(1),
  kind: DesignDocumentKindSchema,
  title: z.string().min(1),
  status: z.string().min(1),
  current_version: z.number().int().nonnegative(),
  created_at: z.string().min(1),
  updated_at: z.string().min(1),
  origin_thread_id: z.string().min(1),
  artifact_type: z.string().min(1).nullable(),
  width_px: z.number().int().positive().nullable(),
  height_px: z.number().int().positive().nullable(),
  account: z
    .object({
      id: z.string().min(1),
      name: z.string().min(1),
      domain: z.string().min(1).nullable(),
      account_entity_id: z.string().min(1).nullable(),
    })
    .nullable(),
  archived_at: z.string().min(1).nullable(),
  saved: z.boolean(),
  last_viewed_at: z.string().min(1).nullable(),
});
export type ArtifactWire = z.infer<typeof ArtifactWireSchema>;

export const ArtifactListResponseSchema = z.object({
  data: z.object({ artifacts: z.array(ArtifactWireSchema) }),
  meta: z.object({ next_cursor: z.string().nullable() }),
});

export interface LibraryAccount {
  id: string;
  name: string;
  domain?: string;
  accountEntityId?: string;
}

export type LibraryArtifact = ProjectArtifact & {
  projectId: string;
  projectTitle: string;
  documentId: string;
  kind: DesignDocumentKind;
  account?: LibraryAccount;
  archivedAt?: string;
  saved: boolean;
};

export interface ArtifactLibraryData {
  artifacts: LibraryArtifact[];
}

export function libraryKey(artifact: { projectId: string; id: string }): string {
  return JSON.stringify([artifact.projectId, artifact.id]);
}

function utcInstant(timestamp: string): string {
  const parsed = new Date(timestamp);
  if (Number.isNaN(parsed.getTime())) throw new TypeError(`artifact timestamp is not a date: ${timestamp}`);
  return parsed.toISOString();
}

// The channel and size rules are the gallery adapter's (imported above), never re-implemented here.

export function toLibraryArtifact(row: ArtifactWire, now = new Date()): LibraryArtifact {
  const ad = row.kind === "ad";
  const collateralType = ad ? collateralTypeFor(row.artifact_type ?? undefined) : "microsite";
  const size = ad ? sizeFor(row.width_px ?? undefined, row.height_px ?? undefined) : undefined;
  const updatedAt = utcInstant(row.updated_at);
  const account: LibraryAccount | undefined = row.account
    ? {
        id: row.account.id,
        name: row.account.name,
        ...(row.account.domain ? { domain: row.account.domain } : {}),
        ...(row.account.account_entity_id ? { accountEntityId: row.account.account_entity_id } : {}),
      }
    : undefined;
  const base = ProjectArtifactSchema.parse({
    ...(collateralType ? { collateralType } : {}),
    ...(size ? { size } : {}),
    ...(account ? { accountId: account.id, accountName: account.name } : {}),
    ...(account?.domain ? { accountLogoPath: `/api/source-favicon?domain=${encodeURIComponent(account.domain)}` } : {}),
    createdAt: utcInstant(row.created_at),
    documentKind: row.kind,
    editedLabel: editedLabelFor(row.updated_at, now),
    id: row.id,
    imagePath: `/api/clue/design/documents/${encodeURIComponent(row.document_id)}/thumbnail?v=${encodeURIComponent(String(row.current_version))}`,
    lastViewedAt: row.last_viewed_at ? utcInstant(row.last_viewed_at) : updatedAt,
    originThreadId: row.origin_thread_id,
    title: row.title,
    type: ad ? "canvas" : "website",
    updatedAt,
  });
  return {
    ...base,
    projectId: row.project_id,
    projectTitle: row.project_title,
    documentId: row.document_id,
    kind: row.kind,
    ...(account ? { account } : {}),
    ...(row.archived_at ? { archivedAt: utcInstant(row.archived_at) } : {}),
    saved: row.saved,
  };
}
