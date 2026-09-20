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

/** The backend's snake_case artifact item, shared by the read and the feed. */
const DesignArtifactItemWireSchema = z.object({
  id: z.string().min(1),
  project_id: z.string().min(1),
  document_id: z.string().min(1),
  kind: z.enum(["web", "ad"]),
  title: z.string().min(1),
  status: z.string().min(1),
  current_version_id: z.string().min(1),
});

/** The backend wire (snake_case envelope) → `ChatShellArtifact`. */
export const DesignArtifactWireSchema = z
  .object({ data: DesignArtifactItemWireSchema })
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

/**
 * One row of the project's design-artifact feed: the read seam's artifact plus
 * what a *listed* artifact needs — its real timestamps and the thread it came
 * from.
 *
 * The feed is leg-derived: a design document belongs to the project whose
 * threads hold the design legs naming it, so `originThreadId` is the thread of
 * the document's latest leg (one thread per document, not all of them).
 * Timestamps arrive as the backend serialized them (Postgres timestamptz, ISO
 * 8601 *with an offset*) — normalizing them is the gallery mapper's job, not
 * the seam's.
 */
export const DesignArtifactListItemSchema = ChatShellArtifactSchema.extend({
  createdAt: z.string().min(1),
  updatedAt: z.string().min(1),
  originThreadId: z.string().min(1),
  /** G-H: the document's recorded artifact type (e.g. `linkedin_square_ad`),
   * absent when it records none. Never inferred. */
  artifactType: z.string().min(1).optional(),
  /** G-H: the document's real page size in px, absent when it has no page. */
  widthPx: z.number().int().positive().optional(),
  heightPx: z.number().int().positive().optional(),
  /**
   * The target account this document was made for, absent when it was made for
   * none. A multi-artifact design leg births one document per account, so the
   * account is what tells two otherwise identical cards apart. `domain` and
   * `accountEntityId` are the account's own optionals — an account the backend
   * knows without them arrives without them, never as an empty string.
   */
  account: z
    .object({
      id: z.string().min(1),
      name: z.string().min(1),
      domain: z.string().min(1).optional(),
      accountEntityId: z.string().min(1).optional(),
      /** Brandfetch's Logo API mark, when the backend could build one. */
      logoPath: z.string().min(1).optional(),
    })
    .optional(),
});

export type DesignArtifactListItem = z.infer<typeof DesignArtifactListItemSchema>;

/** The backend feed wire (snake_case envelope) → `DesignArtifactListItem[]`. */
export const DesignArtifactListWireSchema = z
  .object({
    data: z.array(
      DesignArtifactItemWireSchema.extend({
        created_at: z.string().min(1),
        updated_at: z.string().min(1),
        origin_thread_id: z.string().min(1),
        // G-H: what the DOCUMENT records about itself. Absent when it records
        // nothing — the card then states nothing rather than guessing.
        artifact_type: z.string().min(1).nullish(),
        width_px: z.number().int().positive().nullish(),
        height_px: z.number().int().positive().nullish(),
        // The account the document was made for. Null when it was made for
        // none — the whole object is absent from the item then, the same way
        // the other unanswerable facts are.
        account: z
          .object({
            id: z.string().min(1),
            name: z.string().min(1),
            domain: z.string().min(1).nullish(),
            account_entity_id: z.string().min(1).nullish(),
            logo_path: z.string().min(1).nullish(),
          })
          .nullish(),
      }),
    ),
  })
  .transform(({ data }) =>
    data.map((item) =>
      DesignArtifactListItemSchema.parse({
        id: item.id,
        projectId: item.project_id,
        documentId: item.document_id,
        kind: item.kind,
        title: item.title,
        currentVersionId: item.current_version_id,
        status: item.status,
        createdAt: item.created_at,
        updatedAt: item.updated_at,
        originThreadId: item.origin_thread_id,
        // Absent stays ABSENT (not an `undefined` key): a document that
        // records nothing must be indistinguishable from one this seam never
        // asked about.
        ...(item.artifact_type ? { artifactType: item.artifact_type } : {}),
        ...(item.width_px ? { widthPx: item.width_px } : {}),
        ...(item.height_px ? { heightPx: item.height_px } : {}),
        ...(item.account
          ? {
              account: {
                id: item.account.id,
                name: item.account.name,
                ...(item.account.domain ? { domain: item.account.domain } : {}),
                ...(item.account.account_entity_id
                  ? { accountEntityId: item.account.account_entity_id }
                  : {}),
                ...(item.account.logo_path ? { logoPath: item.account.logo_path } : {}),
              },
            }
          : {}),
      }),
    ),
  );
