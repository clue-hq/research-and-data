// Contract 1 (Wave 2): the stored site document as a Zod schema that the app and the editor
// frame both parse with. Structural only — routes, ids and shapes — so a malformed document is
// refused at the seam instead of half-rendering. What a page may CONTAIN is the site-kit
// validator's job (validate.ts) and the design API's (Contract 2), never this file's.
import { z } from "zod";
import type { BrandData } from "./brand";

/** "/" or "/<name>", the site-kit route rule (validate.ts). */
export const SITE_ROUTE_PATTERN = /^\/(?:[a-z0-9][a-z0-9-]*)?$/;
export const SiteRouteSchema = z.string().regex(SITE_ROUTE_PATTERN);

/** The shared header and footer are addressed as the "shell" target, never as a page route.
 * That is also what makes an annotation's object id `site:shell#header` (Lane A3). */
export const SHELL_TARGET = "shell" as const;
export const SiteTargetSchema = z.union([SiteRouteSchema, z.literal(SHELL_TARGET)]);
export type SiteTarget = z.infer<typeof SiteTargetSchema>;

/** Unique within its page. Letters, digits, "_" and "-" only, so `site:<route>#<id>.<prop>`
 * can never be ambiguous (plan K5). */
export const ComponentIdSchema = z.string().regex(/^[A-Za-z0-9_-]{1,200}$/);
export const SectionDigestSchema = z.string().regex(/^[0-9a-f]{64}$/);
export const AgentSectionNameSchema = z.string().regex(/^[A-Z][A-Za-z0-9]{0,63}$/);

export const SiteComponentSchema = z.looseObject({
  type: z.string().min(1).max(200),
  props: z.looseObject({ id: ComponentIdSchema }),
});

export const SitePageSchema = z.looseObject({
  root: z.looseObject({ props: z.looseObject({ title: z.string().optional() }) }),
  content: z.array(SiteComponentSchema),
  zones: z.record(z.string(), z.unknown()).optional(),
});

/** Plan 6 (ruling R1): the header and footer are sections, stored once per site under these ids. */
export const SHELL_IDS = ["header", "footer"] as const;
export type ShellId = (typeof SHELL_IDS)[number];
export const isShellId = (value: string): value is ShellId => (SHELL_IDS as readonly string[]).includes(value);

/** One of the two: a section entry like a page's, whose id is its place. */
export const ShellEntrySchema = z.looseObject({
  type: z.string().min(1).max(200),
  props: z.looseObject({ id: z.enum(SHELL_IDS) }),
});

export const SiteShellSchema = z.looseObject({
  header: ShellEntrySchema,
  footer: ShellEntrySchema,
});

export const SiteDocumentSchema = z.looseObject({
  id: z.string().min(1),
  title: z.string(),
  theme: z.record(z.string(), z.unknown()).default({}),
  pages: z
    .record(SiteRouteSchema, SitePageSchema)
    .refine((pages) => Object.hasOwn(pages, "/"), { message: "a site always has a home page at /" }),
  // An old-shape shell (before plan 6) opens as no shell rather than refusing the whole site: it draws
  // nothing until the agent rewrites shell.json (ruling R1; there is no migration).
  shell: z.preprocess((value) => (SiteShellSchema.safeParse(value).success ? value : null), SiteShellSchema.nullable()),
  agent_sections: z.record(AgentSectionNameSchema, SectionDigestSchema).default({}),
});

export type SiteComponent = z.infer<typeof SiteComponentSchema>;
export type SitePage = z.infer<typeof SitePageSchema>;
export type ShellEntry = z.infer<typeof ShellEntrySchema>;
export type SiteShell = z.infer<typeof SiteShellSchema>;
export type SiteDocument = z.infer<typeof SiteDocumentSchema>;

/** BrandData as it travels to the editor frame. Shapes only; the design API builds it. */
export const BrandDataSchema = z
  .looseObject({
    slug: z.string(),
    kit: z.record(z.string(), z.unknown()),
    fonts: z.array(
      z.looseObject({ family: z.string(), weight: z.number().nullable(), style: z.string(), file: z.string() }),
    ),
    assets: z.record(z.string(), z.looseObject({ kind: z.string(), file: z.string() })),
    clones: z.record(
      z.string(),
      z.looseObject({
        id: z.string(),
        label: z.string(),
        html: z.string(),
        css: z.string(),
        slots: z.record(z.string(), z.looseObject({ kind: z.string() })),
      }),
    ),
  })
  .transform((value) => value as unknown as BrandData);

/** Contract 4: one agent section the editor may load, with its short-lived link token. */
export const SectionLinkSchema = z.object({
  name: AgentSectionNameSchema,
  digest: SectionDigestSchema,
  token: z.string().regex(/^[A-Za-z0-9._~-]{16,2048}$/),
  propsSchema: z.record(z.string(), z.unknown()),
});
export type SectionLink = z.infer<typeof SectionLinkSchema>;
