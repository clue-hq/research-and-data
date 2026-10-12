import { z } from "zod";
import {
  AgentSectionNameSchema,
  BrandDataSchema,
  SectionDigestSchema,
  SectionLinkSchema,
  SiteDocumentSchema,
} from "@clue/site-kit/site-document";

/** Contract 2: one save is one undo step, one agent turn is one undo step, cap 50. */
export const SITE_UNDO_CAP = 50;

/** `GET /documents/{id}` for a site (plan assumption K4). Anything but `doc_kind: "site"` is
 * refused here, so a site seam can never be handed a scene or a WebDoc. */
export const LoadedSiteWireSchema = z
  .object({
    id: z.string().min(1),
    doc_kind: z.literal("site"),
    title: z.string(),
    scene: SiteDocumentSchema,
    current_version: z.number().int().nonnegative(),
    undo_stack: z.array(z.unknown()).optional(),
    redo_stack: z.array(z.unknown()).optional(),
  })
  .transform((wire) => ({
    documentId: wire.id,
    title: wire.title,
    site: wire.scene,
    version: wire.current_version,
    undoDepth: wire.undo_stack?.length ?? 0,
    redoDepth: wire.redo_stack?.length ?? 0,
  }));
export type LoadedSite = z.output<typeof LoadedSiteWireSchema>;

/** Plan assumption K3: `GET /documents/{id}/site/brand`. */
export const SiteBrandWireSchema = z.object({ brand: BrandDataSchema }).transform((wire) => wire.brand);

/** Contract 4 + plan assumption K2: `POST /documents/{id}/site/section-links`. */
export const SectionLinksWireSchema = z
  .object({
    links: z.array(
      z.object({
        name: AgentSectionNameSchema,
        digest: SectionDigestSchema,
        token: z.string(),
        expires_at: z.string(),
        props_schema: z.record(z.string(), z.unknown()),
      }),
    ),
  })
  .transform((wire) =>
    wire.links.map((link) =>
      SectionLinkSchema.parse({ name: link.name, digest: link.digest, token: link.token, propsSchema: link.props_schema }),
    ),
  );

/** Every Contract 2 write answers with the document's new version. */
export const SiteWriteResultSchema = z
  .object({ document: z.object({ id: z.string().min(1), current_version: z.number().int().nonnegative() }) })
  .transform((wire) => ({ version: wire.document.current_version }));
export type SiteWriteResult = z.output<typeof SiteWriteResultSchema>;

export const SiteVersionsWireSchema = z
  .object({
    versions: z.array(
      z.object({
        batch_id: z.string().min(1),
        version: z.number().int().nonnegative(),
        actor_kind: z.string().min(1),
        intent: z.string().nullable().optional(),
        created_at: z.string().min(1),
      }),
    ),
  })
  .transform((wire) =>
    wire.versions.map((version) => ({
      batchId: version.batch_id,
      version: version.version,
      actorKind: version.actor_kind,
      intent: version.intent ?? null,
      createdAt: version.created_at,
    })),
  );
export type SiteVersion = z.output<typeof SiteVersionsWireSchema>[number];

/** The design API's refusal body: FastAPI `detail`, an object or a bare string. */
export const SiteRefusalSchema = z.object({
  detail: z.union([
    z.string(),
    z.looseObject({
      code: z.string().optional(),
      message: z.string().optional(),
      current_version: z.number().int().optional(),
      errors: z.array(z.string()).optional(),
    }),
  ]),
});
