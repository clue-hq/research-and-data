// The contract for what a page may contain: one Zod schema per component. The editor's fields,
// the validator the agent calls, and the catalog the agent reads all come from these.
//
// Brand theming is enforced here, by structure: style props are token choices only, and every
// object is strict, so a className, style or colour prop cannot be written at all. Text has no
// length limits (founder ruling 2026-10-04: code checks correctness, not prose length).
import { z } from "zod";

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

export const Surface = z.enum(SURFACES);
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

export const PageSchema = z
  .object({
    root: z.object({ props: z.object({ title: text.optional() }).strict() }).strict(),
    content: z.array(item),
    zones: z.record(z.string(), z.unknown()).optional(),
  })
  .strict()
  .superRefine((page, ctx) => {
    page.content.forEach((entry, index) => {
      const schema = COMPONENT_SCHEMAS[entry.type as ComponentType];
      if (!schema) {
        ctx.addIssue({
          code: "custom",
          path: ["content", index, "type"],
          message: `unknown component "${entry.type}"; allowed: ${COMPONENT_TYPES.join(", ")}`,
        });
        return;
      }
      const result = schema.safeParse(entry.props);
      if (!result.success) {
        for (const issue of result.error.issues) {
          ctx.addIssue({ ...issue, path: ["content", index, "props", ...issue.path] } as never);
        }
      }
    });
    const ids = page.content.map((entry) => entry.props.id);
    const duplicate = ids.find((value, index) => ids.indexOf(value) !== index);
    if (duplicate) {
      ctx.addIssue({ code: "custom", path: ["content"], message: `duplicate section id "${String(duplicate)}"` });
    }
  });

export const ShellSchema = z
  .object({
    header: z
      .object({
        id: z.string().optional(),
        preparedFor: text.min(1),
        accountLogo: optionalText,
        ctaLabel: text.min(1),
        ctaHref: link,
        nav: z.array(z.object({ label: text.min(1), href: link }).strict()).max(6).default([]),
      })
      .strict(),
    footer: z
      .object({
        id: z.string().optional(),
        legal: text.min(1),
        privacyHref: optionalLink,
        termsHref: optionalLink,
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
