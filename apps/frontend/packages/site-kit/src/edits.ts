// The one sanctioned place for manual styling (site element inspector, spec §4.3). A section's
// `_edits` prop — and the shell header's and footer's — maps an element key (the element's
// `data-clue-el`) to a style override. The override's schema is strict and closed: brand tokens or
// a hex with an opacity for colour, bounded numbers for sizes and weights, a few fixed choices.
// There is no free CSS, so nothing written here can leave the brand's grammar or break out of a
// selector. A key no element carries is valid: the agent may have rewritten the section, and the
// entry then styles nothing.
import { z } from "zod";
import type { BrandData } from "./brand";
import { colorOf, colorVar, cssString, isComponentToken, tokenGroups, typeSteps, typographyOf } from "./brand-values";
import { ComponentIdSchema } from "./site-document";

/** The reserved prop on a section (and on the shell's header and footer) that holds its edits. */
export const EDITS_PROP = "_edits";
/** The attribute that names a styleable element inside a section. */
export const ELEMENT_KEY_ATTR = "data-clue-el";
/** The attribute on the box around a section (or the shell's header or footer) that scopes its edits. */
export const SECTION_SCOPE_ATTR = "data-clue-section";
/** The key of a section's own box, and of the box inside it that holds the brand's padding (plan 4). */
export const ROOT_KEY = "root";
export const ROOT_INNER_KEY = "root.inner";
/** The scope names of the shell's header and footer. */
export const SHELL_SCOPE = { header: "shell-header", footer: "shell-footer" } as const;

/** An element key: letters, digits, "_", "." and "-", starting with a letter or digit; a styled span
 * of highlighted words (rich.ts) is its element's key plus "~<number>" ("heading~1"). Nothing that
 * could end an attribute selector or start a new rule. */
export const ElementKeySchema = z.string().regex(/^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}(~[0-9]{1,4})?$/);
const KEY_RULE = 'an element key uses letters, digits, "_", "." and "-", starts with a letter or digit, and has up to 100 characters (a styled span\'s key adds "~<number>")';

/** The attribute on a styled span of highlighted words, naming its `_edits` entry (rich.ts). */
export const SPAN_KEY_ATTR = "data-s";
/** Whether a key names a styled span of highlighted words rather than an element. */
export const isSpanKey = (key: string) => key.includes("~");

/** A colour: one of the brand's colour tokens, or a hex colour with an opacity from 0 to 100. */
export const ColorValueSchema = z.union(
  [
    z.object({ token: z.string().min(1).max(100) }).strict(),
    z.object({ hex: z.string().regex(/^#[0-9A-Fa-f]{6}$/), opacity: z.number().int().min(0).max(100) }).strict(),
  ],
  { error: 'a colour is {"token": "<one of the brand\'s colour tokens>"} or {"hex": "#RRGGBB", "opacity": <0 to 100>}' },
);

const corner = z.number().min(0).max(200);
/** A child's key in an `order`: an element, never a styled span. */
const OrderKeySchema = z.string().regex(/^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$/);

/** Properties only the shell's header and footer may set. */
export const SHELL_ONLY_PROPS = ["hidden"] as const;

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
    // Plan 3 (buttons; plan 4 extends them to boxes): the box itself.
    fill: ColorValueSchema.optional(),
    borderColor: ColorValueSchema.optional(),
    borderWidth: z.number().min(0).max(200).optional(),
    /** px; "pill" (fully round ends); or four corners [topLeft, topRight, bottomRight, bottomLeft]. */
    radius: z.union([z.number().min(0).max(200), z.literal("pill"), z.array(corner).length(4)]).optional(),
    /** px all round, or vertical and horizontal. */
    padding: z.union([z.number().min(0).max(200), z.object({ y: z.number().min(0).max(200), x: z.number().min(0).max(200) }).strict()]).optional(),
    /** "fit" (as wide as its content), "fill" (its container's width) or px. */
    width: z.union([z.literal("fit"), z.literal("fill"), z.number().min(1).max(2000)]).optional(),
    // Plan 4 (boxes). The space between a row's or a grid's children.
    gap: z.number().min(0).max(200).optional(),
    /** How the box's contents line up across, stored with the CSS it set (ruling R3): along a row
     * (justify-content), in a stack (align-items), in a grid (justify-items), or plain text (text-align). */
    contentAlign: z
      .object({ along: z.enum(["row", "stack", "grid", "text"]), to: z.enum(["start", "center", "end"]) })
      .strict()
      .optional(),
    /** The order of this box's children, by their keys (spec §4.8): applied to the markup before it is
     * drawn (copied sections and the shell), never as CSS. Keys it does not name keep their places. */
    order: z
      .array(OrderKeySchema)
      .min(1)
      .max(200)
      .refine((keys) => new Set(keys).size === keys.length, { message: "each key once in an order" })
      .optional(),
    /** The header's and footer's parts only (the validator refuses it on a page section): not drawn. */
    hidden: z.literal(true).optional(),
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

/** Every key whose override orders its children, with that order (plan 4). */
export function orderOf(edits: Edits): Record<string, string[]> {
  return Object.fromEntries(Object.entries(edits).flatMap(([key, override]) => (override.order ? [[key, override.order]] : [])));
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
export function brandColorChoices(brand: BrandData): { token: string; value: string }[] {
  return Object.keys(tokenGroups(brand).colors ?? {}).flatMap((token) => {
    const value = colorOf(brand, token);
    return value ? [{ token, value }] : [];
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

/** The font library's families the brand does not already have, in the library's order, each with its
 * weights ascending (plan 2). */
export function libraryFontFamilies(brand: BrandData): { family: string; weights: number[] }[] {
  const own = new Set(brandFontFamilies(brand).map((font) => font.family));
  return (brand.libraryFonts ?? [])
    .filter((font) => !own.has(font.family))
    .map((font) => ({ family: font.family, weights: [...new Set(font.faces.map((face) => face.weight))].sort((a, b) => a - b) }));
}

/** What the brand refuses in these edits, one "<key>: <message>" line each, each saying how to fix
 * it: a colour token the kit does not have, a font family that is not the brand's, and a weight that
 * family does not have (checked only when the override names its family). */
export function editsProblems(edits: Edits, brand: BrandData): string[] {
  const tokens = brandColorChoices(brand).map((choice) => choice.token);
  const own = brandFontFamilies(brand);
  const families = [...own, ...libraryFontFamilies(brand)];
  const problems: string[] = [];
  for (const [key, override] of Object.entries(edits)) {
    for (const [value, word] of [[override.color, "colour"], [override.fill, "fill"], [override.borderColor, "stroke colour"]] as const) {
      if (value && "token" in value && !tokens.includes(value.token)) {
        problems.push(
          `${key}: ${word} token "${value.token}" is not one of this brand's colours; use one of its colour tokens (${tokens.join(", ")}), or a hex colour with an opacity`,
        );
      }
    }
    if (override.fontFamily === undefined) continue;
    const family = families.find((f) => f.family === override.fontFamily);
    if (!family) {
      problems.push(
        families.length
          ? `${key}: "${override.fontFamily}" is not one of this brand's font families or the font library's; use one of ${families.map((f) => f.family).join(", ")}, or leave fontFamily out`
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

/** The CSS fallback for each font library category. */
const LIBRARY_GENERIC: Record<string, string> = { sans: "sans-serif", serif: "serif", slab: "serif", mono: "monospace", display: "sans-serif" };

/** The generic family the kit's own fallback stack gives this family (or, for a library family, its
 * category's); sans-serif when there is none. */
function genericFamily(brand: BrandData, family: string): string {
  const library = brand.libraryFonts?.find((font) => font.family === family);
  if (library && !brandFontFamilies(brand).some((font) => font.family === family)) return LIBRARY_GENERIC[library.category ?? ""] ?? "sans-serif";
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

function radiusCss(radius: StyleOverride["radius"]): string | undefined {
  if (radius === undefined) return undefined;
  if (radius === "pill") return "9999px";
  return typeof radius === "number" ? `${radius}px` : radius.map((value) => `${value}px`).join(" ");
}

/** A hand-set font size (responsive brand type, founder 2026-10-18): in a kit that measured how its
 * type changes with the window, a share of the nearest role's size — the headline's at or above the
 * title size, else the body's — so it is exactly `px` on desktop and shrinks with the seller's own
 * steps on smaller screens (marketers will not check the phone view). Plain px otherwise. */
export function fontSizeCss(brand: BrandData, px: number): string {
  const steps = typeSteps(brand);
  const title = typographyOf(brand, "type.title")?.size;
  const role = title !== undefined && px >= title ? "headline" : "body";
  const size = typographyOf(brand, `type.${role}`)?.size;
  if (!steps?.has(role) || !size) return `${px}px`;
  // CSS divides exactly, so on desktop the size is exactly `px`.
  return `calc(var(--brand-text-${role}) * ${px} / ${size})`;
}

/** How far the brand's headline and body sizes are scaled where an element is drawn now, given the
 * drawn values of their variables (`read`), with the desktop title size that decides which one a
 * hand-set size follows (fontSizeCss); null on desktop and for a kit that did not measure its
 * steps. The editor's frame reports it so the panel shows and takes sizes as drawn in a narrowed
 * preview (responsive brand type, review finding 3). */
export function sizeScaleFrom(
  brand: BrandData,
  read: (role: "headline" | "body") => number,
): { headline: number; body: number; title: number } | null {
  const title = typographyOf(brand, "type.title")?.size;
  if (!typeSteps(brand) || !title) return null;
  const ratio = (role: "headline" | "body") => {
    const desktop = typographyOf(brand, `type.${role}`)?.size;
    const now = read(role);
    return desktop && now > 0 ? Math.round((now / desktop) * 10_000) / 10_000 : 1;
  };
  const headline = ratio("headline");
  const body = ratio("body");
  return headline === 1 && body === 1 ? null : { body, headline, title };
}

const FLEX_ALIGN = { start: "flex-start", center: "center", end: "flex-end" } as const;
const TEXT_ALIGN = { start: "left", center: "center", end: "right" } as const;

/** Content alignment as the one property it was set as (ruling R3). */
function alignCss(align: StyleOverride["contentAlign"]): [string, string | undefined][] {
  if (!align) return [];
  if (align.along === "row") return [["justify-content", FLEX_ALIGN[align.to]]];
  if (align.along === "stack") return [["align-items", FLEX_ALIGN[align.to]]];
  if (align.along === "grid") return [["justify-items", align.to]];
  return [["text-align", TEXT_ALIGN[align.to]]];
}

/** One element's override as CSS declarations, in the schema's order. */
function declarations(brand: BrandData, override: StyleOverride): string[] {
  const out: [string, string | undefined][] = [
    ["color", override.color && colorCss(brand, override.color)],
    ["font-family", override.fontFamily && cssString(override.fontFamily) ? `"${cssString(override.fontFamily)}", ${genericFamily(brand, override.fontFamily)}` : undefined],
    ["font-size", override.fontSize !== undefined ? fontSizeCss(brand, override.fontSize) : undefined],
    ["font-weight", override.fontWeight !== undefined ? String(override.fontWeight) : undefined],
    // Off is a value too: it undoes italic or underline the element has by default (an <em>, a link).
    ["font-style", override.italic === undefined ? undefined : override.italic ? "italic" : "normal"],
    ["text-decoration-line", override.underline === undefined ? undefined : override.underline ? "underline" : "none"],
    ["text-align", override.textAlign],
    ["background-color", override.fill && colorCss(brand, override.fill)],
    // A fill replaces the box's own colour entirely: a gradient button turns flat.
    ["background-image", override.fill && colorCss(brand, override.fill) ? "none" : undefined],
    ["border-color", override.borderColor && colorCss(brand, override.borderColor)],
    ["border-width", override.borderWidth !== undefined ? `${override.borderWidth}px` : undefined],
    ["border-style", override.borderWidth !== undefined ? "solid" : undefined],
    ["border-radius", radiusCss(override.radius)],
    ["padding", override.padding === undefined ? undefined : typeof override.padding === "number" ? `${override.padding}px` : `${override.padding.y}px ${override.padding.x}px`],
    ["width", override.width === undefined ? undefined : override.width === "fit" ? "fit-content" : override.width === "fill" ? "100%" : `${override.width}px`],
    ["gap", override.gap !== undefined ? `${override.gap}px` : undefined],
    ...alignCss(override.contentAlign),
    ["display", override.hidden ? "none" : undefined],
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
  return libraryFaces(edits, brand) + Object.entries(edits)
    .flatMap(([key, value]) => {
      const override = StyleOverrideSchema.safeParse(value);
      if (!ElementKeySchema.safeParse(key).success || !override.success) return [];
      const css = declarations(brand, override.data);
      const attr = isSpanKey(key) ? SPAN_KEY_ATTR : ELEMENT_KEY_ATTR;
      const inside = `[${SECTION_SCOPE_ATTR}="${scope}"] [${attr}="${key}"]`;
      // A section's own box (plan 4, `root`) may be the scoped element itself: the shell's header and
      // footer carry their scope on the box. Same specificity either way.
      const selector = key === ROOT_KEY ? `[${SECTION_SCOPE_ATTR}="${scope}"][${attr}="${key}"],${inside}` : inside;
      return css.length ? [`${selector}{${css.join(";")}}`] : [];
    })
    .join("");
}

const FACE_FILE = /^[A-Za-z0-9._~/-]+$/;
const FACE_STYLES = new Set(["normal", "italic", "oblique"]);

/** The `@font-face` rules of the library families these edits use (the brand's own are the theme's):
 * each family once, every face of it (the browser fetches only the faces it draws). A face whose file,
 * style or weight is not plainly one is skipped, as the theme skips one. */
function libraryFaces(edits: Edits, brand: BrandData): string {
  const own = new Set(brandFontFamilies(brand).map((font) => font.family));
  const used = new Set(
    Object.values(edits).flatMap((value) => {
      const family = StyleOverrideSchema.safeParse(value).data?.fontFamily;
      return family && !own.has(family) ? [family] : [];
    }),
  );
  return (brand.libraryFonts ?? [])
    .filter((font) => used.has(font.family))
    .flatMap((font) => {
      const family = cssString(font.family);
      if (!family) return [];
      return font.faces
        .filter((face) => FACE_FILE.test(face.file) && FACE_STYLES.has(face.style) && Number.isInteger(face.weight) && face.weight >= 1 && face.weight <= 1000)
        .map((face) => `@font-face{font-family:"${family}";src:url("${face.file}");font-weight:${face.weight};font-style:${face.style};font-display:swap}`);
    })
    .join("");
}
