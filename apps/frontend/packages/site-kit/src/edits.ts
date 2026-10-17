// The one sanctioned place for manual styling (site element inspector, spec §4.3). A section's
// `_edits` prop — and the shell header's and footer's — maps an element key (the element's
// `data-clue-el`) to a style override. The override's schema is strict and closed: brand tokens or
// a hex with an opacity for colour, bounded numbers for sizes and weights, a few fixed choices.
// There is no free CSS, so nothing written here can leave the brand's grammar or break out of a
// selector. A key no element carries is valid: the agent may have rewritten the section, and the
// entry then styles nothing.
import { z } from "zod";
import type { BrandData } from "./brand";
import { colorOf, colorVar, cssString, isComponentToken, tokenGroups } from "./brand-values";
import { ComponentIdSchema } from "./site-document";

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

/** The CSS generic families a kit's fallback stack may end in. */
const GENERIC_FAMILIES = new Set([
  "serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui",
  "ui-serif", "ui-sans-serif", "ui-monospace", "ui-rounded", "math", "emoji", "fangsong",
]);

/** The generic family the kit's own fallback stack gives this family; sans-serif when it gives none
 * (or the family is not the kit's). */
function genericFamily(brand: BrandData, family: string): string {
  const fonts = (brand.kit as { assets?: { fonts?: Record<string, { family?: string; fallback_stack?: string[] }> } }).assets?.fonts ?? {};
  const stack = Object.values(fonts).find((font) => font.family === family)?.fallback_stack ?? [];
  return stack.map((name) => String(name).trim().toLowerCase()).find((name) => GENERIC_FAMILIES.has(name)) ?? "sans-serif";
}

/** A colour as CSS: a token through the theme's root variable, or the kit's colour itself for a
 * component token (the theme draws those inline, so they have no variable); a hex with its opacity
 * as #RRGGBBAA. A token the kit does not have gives nothing. */
function colorCss(brand: BrandData, color: ColorValue): string | undefined {
  if ("hex" in color) {
    const alpha = Math.round((color.opacity * 255) / 100).toString(16).padStart(2, "0");
    return `${color.hex}${alpha}`.toUpperCase();
  }
  const value = colorOf(brand, color.token);
  if (!value) return undefined;
  return isComponentToken(color.token) ? value : `var(--brand-${colorVar(color.token)})`;
}

/** One element's override as CSS declarations, in the schema's order. */
function declarations(brand: BrandData, override: StyleOverride): string[] {
  const out: [string, string | undefined][] = [
    ["color", override.color && colorCss(brand, override.color)],
    ["font-family", override.fontFamily && cssString(override.fontFamily) ? `"${cssString(override.fontFamily)}", ${genericFamily(brand, override.fontFamily)}` : undefined],
    ["font-size", override.fontSize !== undefined ? `${override.fontSize}px` : undefined],
    ["font-weight", override.fontWeight !== undefined ? String(override.fontWeight) : undefined],
    // Off is a value too: it undoes italic or underline the element has by default (an <em>, a link).
    ["font-style", override.italic === undefined ? undefined : override.italic ? "italic" : "normal"],
    ["text-decoration-line", override.underline === undefined ? undefined : override.underline ? "underline" : "none"],
    ["text-align", override.textAlign],
  ];
  return out.flatMap(([property, value]) => (value ? [`${property}:${value} !important`] : []));
}

/** A section's edits as its scoped stylesheet (spec §4.5): one rule per element,
 * `[data-clue-section="<scope>"] [data-clue-el="<key>"]{…}`, drawn beside the section in the editor
 * and on the published page alike. Every declaration is !important: the clones' own CSS is not in a
 * layer, so only an important rule beats it (and the theme and Tailwind's utilities with it). A scope
 * that is not a section id, a key or an override the schema refuses, and a value the brand cannot
 * resolve each emit nothing; "" when nothing is left. */
export function editsCss(scope: string, edits: Edits, brand: BrandData): string {
  if (!ComponentIdSchema.safeParse(scope).success) return "";
  return Object.entries(edits)
    .flatMap(([key, value]) => {
      const override = StyleOverrideSchema.safeParse(value);
      if (!ElementKeySchema.safeParse(key).success || !override.success) return [];
      const css = declarations(brand, override.data);
      return css.length ? [`[${SECTION_SCOPE_ATTR}="${scope}"] [${ELEMENT_KEY_ATTR}="${key}"]{${css.join(";")}}`] : [];
    })
    .join("");
}
