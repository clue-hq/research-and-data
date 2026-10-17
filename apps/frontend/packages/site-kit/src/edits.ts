// The one sanctioned place for manual styling (site element inspector, spec §4.3). A section's
// `_edits` prop — and the shell header's and footer's — maps an element key (the element's
// `data-clue-el`) to a style override. The override's schema is strict and closed: brand tokens or
// a hex with an opacity for colour, bounded numbers for sizes and weights, a few fixed choices.
// There is no free CSS, so nothing written here can leave the brand's grammar or break out of a
// selector. A key no element carries is valid: the agent may have rewritten the section, and the
// entry then styles nothing.
import { z } from "zod";
import type { BrandData } from "./brand";
import { colorOf, tokenGroups } from "./brand-values";

/** The reserved prop on a section (and on the shell's header and footer) that holds its edits. */
export const EDITS_PROP = "_edits";
/** The attribute that names a styleable element inside a section. */
export const ELEMENT_KEY_ATTR = "data-clue-el";
/** The attribute on the box around a section (or the shell's header or footer) that scopes its edits. */
export const SECTION_SCOPE_ATTR = "data-clue-section";
/** The scope names of the shell's header and footer. */
export const SHELL_SCOPE = { header: "shell-header", footer: "shell-footer" } as const;

/** An element key: letters, digits, "_", "." and "-", starting with a letter or digit. Nothing that
 * could end an attribute selector or start a new rule. */
export const ElementKeySchema = z.string().regex(/^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$/);
const KEY_RULE = 'an element key uses letters, digits, "_", "." and "-", starts with a letter or digit, and has up to 100 characters';

/** A colour: one of the brand's colour tokens, or a hex colour with an opacity from 0 to 100. */
export const ColorValueSchema = z.union(
  [
    z.object({ token: z.string().min(1).max(100) }).strict(),
    z.object({ hex: z.string().regex(/^#[0-9A-Fa-f]{6}$/), opacity: z.number().int().min(0).max(100) }).strict(),
  ],
  { error: 'a colour is {"token": "<one of the brand\'s colour tokens>"} or {"hex": "#RRGGBB", "opacity": <0 to 100>}' },
);

/** One element's manual styling. Every property is optional; bold is fontWeight 700. */
export const StyleOverrideSchema = z
  .object({
    color: ColorValueSchema.optional(),
    fontFamily: z.string().min(1).max(100).optional(),
    fontSize: z.number().min(8).max(200).optional(),
    fontWeight: z.number().int().min(100).max(900).multipleOf(100).optional(),
    italic: z.boolean().optional(),
    underline: z.boolean().optional(),
    textAlign: z.enum(["left", "center", "right", "justify"]).optional(),
  })
  .strict();

export const EditsSchema = z.record(ElementKeySchema, StyleOverrideSchema, {
  error: (issue) => (issue.code === "invalid_key" ? KEY_RULE : undefined),
});

export type ColorValue = z.infer<typeof ColorValueSchema>;
export type StyleOverride = z.infer<typeof StyleOverrideSchema>;
export type Edits = z.infer<typeof EditsSchema>;

/** The props' `_edits`, parsed; {} when there is none or it is not valid (the validator reports it). */
export function editsOf(props: Record<string, unknown>): Edits {
  const result = EditsSchema.safeParse(props[EDITS_PROP]);
  return result.success ? result.data : {};
}

/** The props without `_edits`: what a section's own schema and its render see. */
export function withoutEdits<T extends Record<string, unknown>>(props: T): Omit<T, "_edits"> {
  const { _edits: _, ...rest } = props;
  return rest;
}

/** The edits with one element's override replaced. A property set to undefined is dropped, and an
 * element whose override ends up empty is dropped with it. The given edits are not changed. */
export function withStyleOverride(edits: Edits, key: string, override: StyleOverride): Edits {
  const kept = Object.fromEntries(Object.entries(override).filter(([, value]) => value !== undefined)) as StyleOverride;
  const { [key]: _, ...rest } = edits;
  return Object.keys(kept).length ? { ...rest, [key]: kept } : rest;
}

/** Every colour token of the kit that resolves to a colour, in the kit's order, with its value as
 * the theme writes it (colorOf: upper-case hex, or oklch() for a kit that stores oklch). */
export function brandColorChoices(brand: BrandData): { token: string; hex: string }[] {
  return Object.keys(tokenGroups(brand).colors ?? {}).flatMap((token) => {
    const hex = colorOf(brand, token);
    return hex ? [{ token, hex }] : [];
  });
}

/** The brand's font families, in the order the kit lists their faces, each with its weights
 * ascending. A face with no weight is drawn as 400 (themeCss), so it counts as 400. */
export function brandFontFamilies(brand: BrandData): { family: string; weights: number[] }[] {
  const families = new Map<string, Set<number>>();
  for (const face of brand.fonts) {
    const weights = families.get(face.family) ?? new Set<number>();
    weights.add(face.weight ?? 400);
    families.set(face.family, weights);
  }
  return [...families].map(([family, weights]) => ({ family, weights: [...weights].sort((a, b) => a - b) }));
}

/** What the brand refuses in these edits, one "<key>: <message>" line each, each saying how to fix
 * it: a colour token the kit does not have, a font family that is not the brand's, and a weight that
 * family does not have (checked only when the override names its family). */
export function editsProblems(edits: Edits, brand: BrandData): string[] {
  const tokens = brandColorChoices(brand).map((choice) => choice.token);
  const families = brandFontFamilies(brand);
  const problems: string[] = [];
  for (const [key, override] of Object.entries(edits)) {
    const color = override.color;
    if (color && "token" in color && !tokens.includes(color.token)) {
      problems.push(
        `${key}: colour token "${color.token}" is not one of this brand's colours; use one of its colour tokens (${tokens.join(", ")}), or a hex colour with an opacity`,
      );
    }
    if (override.fontFamily === undefined) continue;
    const family = families.find((f) => f.family === override.fontFamily);
    if (!family) {
      problems.push(
        families.length
          ? `${key}: "${override.fontFamily}" is not one of this brand's font families; use one of ${families.map((f) => f.family).join(", ")}, or leave fontFamily out`
          : `${key}: this brand's kit has no font files, so "${override.fontFamily}" cannot be used; leave fontFamily out`,
      );
      continue;
    }
    if (override.fontWeight !== undefined && !family.weights.includes(override.fontWeight)) {
      problems.push(
        `${key}: ${family.family} has no weight ${override.fontWeight}; use one of its weights (${family.weights.join(", ")}), or leave fontWeight out`,
      );
    }
  }
  return problems;
}
