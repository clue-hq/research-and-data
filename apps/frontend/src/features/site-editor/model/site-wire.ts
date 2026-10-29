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

/** Stands in for a section's own scoping class in the brand's shared CSS blocks (design API
 * `site_brand.CLONE_CLASS_MARK`). */
export const CLONE_CLASS_MARK = "\u0000";

/** Site loading (2026-10-29, schema 2): the design API sends each distinct top-level CSS block of
 * the brand's sections once, in `css_rules`, and each section names its blocks by index in its own
 * `css_rules`, its scoping class stood in by `CLONE_CLASS_MARK`. This puts every section's `css`
 * back exactly; a section sent with its `css` as it is (and a schema 1 answer) is left alone. */
function withCloneCss(wire: unknown): unknown {
  if (typeof wire !== "object" || wire === null) return wire;
  const { brand, css_rules: rules } = wire as { brand?: { clones?: Record<string, Record<string, unknown>> }; css_rules?: unknown };
  if (!Array.isArray(rules) || !brand?.clones) return wire;
  const clones = Object.fromEntries(
    Object.entries(brand.clones).map(([key, clone]) => {
      const refs = clone.css_rules;
      if (!Array.isArray(refs)) return [key, clone];
      const blocks = refs.map((ref) => {
        const block: unknown = rules[ref as number];
        if (typeof block !== "string") throw new Error(`section ${key} names CSS block ${String(ref)}, which the answer does not hold`);
        return block;
      });
      const rest = { ...clone };
      delete rest.css_rules;
      return [key, { ...rest, css: blocks.join("").replaceAll(CLONE_CLASS_MARK, String(clone.wrapper_class)) }];
    }),
  );
  return { ...wire, brand: { ...brand, clones } };
}

/** Plan assumption K3: `GET /documents/{id}/site/brand` — only the sections the site places, their
 * CSS packed (`withCloneCss`). */
export const SiteBrandWireSchema = z
  .preprocess(withCloneCss, z.object({ brand: BrandDataSchema }))
  .transform((wire) => wire.brand);

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
