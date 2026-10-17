// The contract for what a page may contain: one Zod schema per component. The editor's fields,
// the validator the agent calls, and the catalog the agent reads all come from these.
//
// Brand theming is enforced here, by structure: style props are token choices only, and every
// object is strict, so a className, style or colour prop cannot be written at all. The one place
// for manual styling is each section's (and the shell's) `_edits` prop, itself a closed schema of
// brand tokens and bounded values (edits.ts). Text has no length limits (founder ruling 2026-10-04:
// code checks correctness, not prose length).
import { z } from "zod";
import { EDITS_PROP, EditsSchema, withoutEdits } from "./edits";
import { ComponentIdSchema } from "./site-document";

export const SURFACES = ["page", "card", "muted", "brandSubtle", "brand", "inverse"] as const;
export const SURFACE_LABELS: Record<(typeof SURFACES)[number], string> = {
  page: "Page",
  card: "Card",
  muted: "Muted",
  brandSubtle: "Brand, subtle",
  brand: "Brand",
  inverse: "Inverse",
};
export const HEADING_ROLES = ["display", "headline", "title"] as const;

/** A surface by its choice name: one of our six, or one of this brand's other surfaces ("canvas",
 * "band-014036"). The validator checks it against the brand (founder Q4 = (b)). */
export const Surface = z.string().min(1);
/** A button style by its recipe's name ("solid.047464"; a kit made before measurement says
 * "outline.1"); empty is the kit's standard button. The validator checks it against the brand
 * (founder ruling 4). */
const buttonLook = z.string().default("");
export const HeadingRole = z.enum(HEADING_ROLES);

const id = z.string().min(1);
const text = z.string();
const optionalText = z.string().default("");
const link = z
  .string()
  .refine((value) => value === "" || /^(https?:\/\/|\/|#|mailto:)/.test(value), {
    message: "must be empty, an https:// URL, a /route on this site, or a #anchor",
  });
const optionalLink = link.default("");
/** An image is a file from the brand's asset list; the validator checks membership. */
const image = z.string().default("");

export const StatsBandSchema = z
  .object({
    id,
    surface: Surface,
    align: z.enum(["left", "center"]).default("left"),
    eyebrow: optionalText,
    heading: text.min(1),
    intro: optionalText,
    stats: z.array(z.object({ value: text.min(1), label: text }).strict()).min(1).max(4),
    source: optionalText,
  })
  .strict();

export const FeatureSplitSchema = z
  .object({
    id,
    surface: Surface,
    eyebrow: optionalText,
    heading: text.min(1),
    headingRole: HeadingRole.default("title"),
    body: text.min(1),
    image,
    imageSide: z.enum(["left", "right"]).default("left"),
    buttonLabel: optionalText,
    buttonHref: optionalLink,
    buttonLook,
  })
  .strict();

export const ProofCardSchema = z
  .object({
    id,
    surface: Surface,
    kicker: text.min(1),
    metric: text.min(1),
    metricLabel: text.min(1),
    heading: text.min(1),
    body: optionalText,
    source: optionalText,
    linkLabel: optionalText,
    linkHref: optionalLink,
  })
  .strict();

export const CtaBandSchema = z
  .object({
    id,
    surface: Surface,
    heading: text.min(1),
    body: optionalText,
    buttonLabel: text.min(1),
    buttonHref: link,
    buttonLook,
  })
  .strict();

export const ClonedSectionSchema = z
  .object({
    id,
    fragmentId: z
      .string()
      .regex(/^frag_[0-9a-f]{16}$/, "must be a clone id from the catalog (frag_ and 16 hex characters)"),
    slots: z.record(z.string(), z.union([z.string(), z.boolean()])).default({}),
    replacements: z.array(z.object({ find: text.min(1), replace: text }).strict()).default([]),
    links: z.array(z.object({ find: text.min(1), replace: link }).strict()).default([]),
  })
  .strict();

/** Every component a page may use. Anything else is refused. */
export const COMPONENT_SCHEMAS = {
  ClonedSection: ClonedSectionSchema,
  StatsBand: StatsBandSchema,
  FeatureSplit: FeatureSplitSchema,
  ProofCard: ProofCardSchema,
  CtaBand: CtaBandSchema,
} as const;
export type ComponentType = keyof typeof COMPONENT_SCHEMAS;
export const COMPONENT_TYPES = Object.keys(COMPONENT_SCHEMAS) as ComponentType[];

const item = z.object({ type: z.string(), props: z.record(z.string(), z.unknown()) }).strict();


/** The page schema, optionally with extra section types (a site's agent-written sections, E5). */
export function pageSchemaWith(extra: Record<string, z.ZodType> = {}) {
  const schemas: Record<string, z.ZodType> = { ...COMPONENT_SCHEMAS, ...extra };
  const allowed = Object.keys(schemas);
  return z
  .object({
    root: z.object({ props: z.object({ title: text.optional() }).strict() }).strict(),
    content: z.array(item),
    zones: z.record(z.string(), z.unknown()).optional(),
  })
  .strict()
  .superRefine((page, ctx) => {
    page.content.forEach((entry, index) => {
      // Controller ruling R10: the editor and the composer address a section as
      // site:<route>#<id>.<field>, so an id may never carry "#", "." or anything else. The rule is
      // the editor's own (ComponentIdSchema), checked whatever the section's schema says: an agent
      // section whose id is optional, a number or a default used to save and then fail to open in
      // the editor (review finding K1-2).
      const sectionId = entry.props.id;
      if (typeof sectionId !== "string" || sectionId === "") {
        ctx.addIssue({
          code: "custom",
          path: ["content", index, "props", "id"],
          message: 'every section needs an id: letters, digits, "-" and "_" (up to 200 characters)',
        });
      } else if (!ComponentIdSchema.safeParse(sectionId).success) {
        ctx.addIssue({
          code: "custom",
          path: ["content", index, "props", "id"],
          message: `a section id may use only letters, digits, "-" and "_" (up to 200 characters); "${sectionId}" does not`,
        });
      }
      const schema = schemas[entry.type];
      if (!schema) {
        ctx.addIssue({
          code: "custom",
          path: ["content", index, "type"],
          message: `unknown component "${entry.type}"; allowed: ${allowed.join(", ")}`,
        });
        return;
      }
      // `_edits` is every section's, whatever its own schema (an agent section's is usually
      // strict): the section's schema checks the props without it, and the edits schema checks it.
      const result = schema.safeParse(withoutEdits(entry.props));
      if (!result.success) {
        for (const issue of result.error.issues) {
          ctx.addIssue({ ...issue, path: ["content", index, "props", ...issue.path] } as never);
        }
      }
      if (entry.props[EDITS_PROP] !== undefined) {
        const edits = EditsSchema.safeParse(entry.props[EDITS_PROP]);
        if (!edits.success) {
          for (const issue of edits.error.issues) {
            ctx.addIssue({ ...issue, path: ["content", index, "props", EDITS_PROP, ...issue.path] } as never);
          }
        }
      }
    });
    const ids = page.content.map((entry) => entry.props.id);
    const duplicate = ids.find((value, index) => ids.indexOf(value) !== index);
    if (duplicate) {
      ctx.addIssue({ code: "custom", path: ["content"], message: `duplicate section id "${String(duplicate)}"` });
    }
  });
}

export const PageSchema = pageSchemaWith();

export const ShellSchema = z
  .object({
    header: z
      .object({
        id: z.string().optional(),
        preparedFor: text.min(1),
        accountLogo: optionalText,
        ctaLabel: text.min(1),
        ctaHref: link,
        ctaLook: buttonLook,
        nav: z.array(z.object({ label: text.min(1), href: link }).strict()).max(6).default([]),
        _edits: EditsSchema.optional(),
      })
      .strict(),
    footer: z
      .object({
        id: z.string().optional(),
        legal: text.min(1),
        privacyHref: optionalLink,
        termsHref: optionalLink,
        _edits: EditsSchema.optional(),
      })
      .strict(),
  })
  .strict();

/** One line per issue: where it is and what is wrong, in words the agent can act on. */
export function formatIssues(error: z.ZodError): string {
  return error.issues
    .map((issue) => {
      const where = issue.path.length ? issue.path.join(".") : "(page)";
      return `${where}: ${issue.message}`;
    })
    .join("\n");
}
