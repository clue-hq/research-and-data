// The brand kit's values, resolved. Every style value site-kit draws comes from here: a token of the
// kit (measured on the seller's site, or derived by the kit) or, only where the kit has none, one of
// FALLBACKS — each named where the agent can see it (brand.md). Components carry no style value of
// their own (test/style-literals.test.ts).
import type { BrandData } from "./brand";

type TokenDefault = { kind?: string; [key: string]: unknown };
export type TokenEntry = {
  value?: { default?: TokenDefault; modes?: Record<string, TokenDefault> };
  role?: string | null;
  description?: string | null;
  provenance?: { source?: string; confidence?: number } | null;
};
export type TokenGroups = Partial<Record<string, Record<string, TokenEntry>>>;

/** The only style values site-kit supplies itself, each used only where the kit has no value. */
export const FALLBACKS = {
  /** No kit token holds a button's padding (block, inline); brand.md says when it is drawn. */
  buttonPadding: ["0.75em", "1.5em"],
  /** An outline style whose border width the kit did not record. */
  outlineWidth: "1px",
  /** A button or a link card the kit gave no decoration is not underlined. */
  controlDecoration: "none",
  /** A text link the kit never measured stays visibly a link; brand.md says so. */
  linkDecoration: "underline",
  /** No kit token holds a page's content width. */
  contentWidth: "75rem",
  /** The kit records logos, not the size they are shown at in the header and footer. */
  headerLogoHeight: "1.75rem",
  footerLogoHeight: "1.25rem",
  /** Used only when the kit has no stroke.width.divider. */
  ruleWidth: "1px",
  /** Sizes are exact at the width the kit measured at; above `fixedUpToPx` they shrink on smaller
   * screens, to `minShare` of themselves at the least. */
  fluid: { fixedUpToPx: 24, minShare: 0.5, measuredAtPx: 1440 },
} as const;

export const COMPONENT_TOKEN_ROOTS = ["button", "link", "navlink", "card", "chip", "input", "image", "motion"] as const;
export const isComponentToken = (name: string) => (COMPONENT_TOKEN_ROOTS as readonly string[]).includes(name.split(".")[0]);

/** The engine's token-path charset. A kit's token names become CSS custom-property names and class
 * selectors (`--brand-surface-band-014036`, `.bg-surface-band-014036`), so a name outside it is never
 * read: tokenGroups drops it, and every read of a kit token starts there. */
const TOKEN_PATH = /^[A-Za-z0-9_.-]+$/;
/** Each kit's groups, read once: a kit is data, and nothing edits one in place after reading it. */
const readGroups = new WeakMap<object, TokenGroups>();

export function tokenGroups(brand: BrandData): TokenGroups {
  const raw = (brand.kit as { tokens?: unknown }).tokens;
  if (typeof raw !== "object" || raw === null) return {};
  let groups = readGroups.get(raw);
  if (!groups) {
    groups = Object.fromEntries(
      Object.entries(raw as TokenGroups).map(([group, entries]) => [group, Object.fromEntries(Object.entries(entries ?? {}).filter(([name]) => TOKEN_PATH.test(name)))]),
    );
    readGroups.set(raw, groups);
  }
  return groups;
}

export function tokenEntry(brand: BrandData, group: string, name: string | null | undefined): TokenEntry | undefined {
  return name ? tokenGroups(brand)[group]?.[name] : undefined;
}

/** Measured on the seller's site (any capture source), rather than derived or defaulted by the kit. */
export function isMeasured(entry: TokenEntry | undefined): boolean {
  const source = entry?.provenance?.source ?? "";
  return source !== "" && !source.startsWith("derived:") && !source.startsWith("default:");
}

export const trim = (n: number) => String(Math.round(n * 1000) / 1000);
const HEX = /^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$/;
const MAX_ALIAS_HOPS = 8;

function resolved(brand: BrandData, group: string, name: string | null | undefined, hops = 0): TokenDefault | undefined {
  const value = tokenEntry(brand, group, name)?.value?.default;
  if (!value || hops > MAX_ALIAS_HOPS) return undefined;
  if (value.kind === "alias" && typeof value.token === "string") return resolved(brand, group, value.token, hops + 1);
  return value;
}

/** A colour token as CSS: hex, or oklch(). */
export function colorOf(brand: BrandData, name: string | null | undefined): string | undefined {
  const value = resolved(brand, "colors", name);
  if (value?.kind === "hex" && typeof value.value === "string" && HEX.test(value.value)) return value.value.toUpperCase();
  if (value?.kind === "oklch" && [value.l, value.c, value.h].every((n) => typeof n === "number")) {
    return `oklch(${value.l} ${value.c} ${value.h} / ${typeof value.alpha === "number" ? value.alpha : 1})`;
  }
  return undefined;
}

/** The hex behind a colour token, for contrast maths. */
export function hexOf(brand: BrandData, name: string | null | undefined): string | undefined {
  const value = colorOf(brand, name);
  return value?.startsWith("#") ? value : undefined;
}

const NUMBER_GROUPS = ["spacing", "radii", "stroke_widths", "opacity", "numbers"] as const;

export function numberOf(brand: BrandData, name: string | null | undefined): { value: number; unit: string } | undefined {
  for (const group of NUMBER_GROUPS) {
    const value = resolved(brand, group, name);
    if (value?.kind === "number" && typeof value.value === "number" && Number.isFinite(value.value)) {
      return { value: value.value, unit: String(value.unit ?? "unitless") };
    }
  }
  return undefined;
}

export function pxOf(brand: BrandData, name: string | null | undefined): string | undefined {
  const n = numberOf(brand, name);
  return n && n.unit === "px" ? `${trim(n.value)}px` : undefined;
}

export function ratioOf(brand: BrandData, name: string | null | undefined): string | undefined {
  const n = numberOf(brand, name);
  return n && (n.unit === "ratio" || n.unit === "unitless") ? trim(n.value) : undefined;
}

export type TypeStyle = {
  family: string; size: number; weight: number; lineHeight: number | null; letterSpacing: number | null;
  color: string | null; asset: string | null;
};

export function typographyOf(brand: BrandData, name: string | null | undefined): TypeStyle | undefined {
  const value = resolved(brand, "typography", name);
  if (value?.kind !== "style" || typeof value.font_family !== "string" || typeof value.font_size !== "number") return undefined;
  return {
    family: value.font_family,
    size: value.font_size,
    weight: Number(value.font_weight ?? 400),
    lineHeight: typeof value.line_height === "number" ? value.line_height : null,
    letterSpacing: typeof value.letter_spacing === "number" ? value.letter_spacing : null,
    color: typeof value.color === "string" ? value.color : null,
    asset: typeof value.font_asset === "string" ? value.font_asset : null,
  };
}

/** A font family as the text of a CSS string: no quote, backslash, angle bracket, semicolon, brace
 * or control character (a family is kept verbatim from the seller's CSS, and it is written into a
 * <style> element), whitespace runs as one space. Empty means there is no family to write. */
export function cssString(text: string): string {
  return text.replace(/["'\\<>;{}\x00-\x1f\x7f]/g, "").replace(/\s+/g, " ").trim();
}

/** The family, then the kit's own fallback stack for that font; nothing invented. */
export function fontStack(brand: BrandData, style: TypeStyle): string {
  const fonts = (brand.kit as { assets?: { fonts?: Record<string, { family?: string; fallback_stack?: string[] }> } }).assets?.fonts ?? {};
  const font = (style.asset ? fonts[style.asset] : undefined) ?? Object.values(fonts).find((f) => f.family === style.family);
  const names = [style.family, ...(font?.fallback_stack ?? [])]
    .map((name) => cssString(String(name ?? "")))
    .filter((name, i, all) => name && all.indexOf(name) === i);
  return names.map((name) => (/^[a-z-]+$/.test(name) ? name : `"${name}"`)).join(", ");
}

export function shadowOf(brand: BrandData, name: string | null | undefined): string | undefined {
  const value = tokenEntry(brand, "shadows", name)?.value?.default as
    | { x?: number; y?: number; blur?: number; spread?: number; color?: string } | undefined;
  if (!value || typeof value.color !== "string" || !HEX.test(value.color)) return undefined;
  return `${trim(value.x ?? 0)}px ${trim(value.y ?? 0)}px ${trim(value.blur ?? 0)}px ${trim(value.spread ?? 0)}px ${value.color.toUpperCase()}`;
}

export type StyleValue =
  | { kind: "keyword"; property: string; value: string }
  | { kind: "duration"; ms: number }
  | { kind: "easing"; function: string }
  | { kind: "transform"; value: string }
  | { kind: "keyframes"; frames: { offset: number; declarations: Record<string, string> }[] }
  | { kind: "animation"; keyframes: string; duration: string; easing: string; delay: string | null; iterations: string; direction: string; fill_mode: string }
  | { kind: "reveal"; from_opacity: string | null; from_transform: string | null; duration: string; easing: string }
  | { kind: "glyph"; text: string }
  | { kind: "svg"; markup: string; width: number; height: number };

const SAFE_CSS = /^[A-Za-z0-9 ,.()%#+\-/]{1,400}$/;
/** A CSS value that only draws: plain characters, nothing that loads or substitutes. */
export const safeCss = (value: string) => SAFE_CSS.test(value) && !/url\(|var\(|expression/i.test(value);
/** The elements that draw; with `svg` and `g`, every element an icon may use (the engine's lists). */
const ICON_DRAWING_ELEMENTS = new Set(["path", "circle", "ellipse", "line", "polyline", "polygon", "rect"]);
/** The attributes, spelled exactly as ingestion's cleaner writes them. */
const ICON_ATTRIBUTES = new Set([
  "viewBox", "d", "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "stroke-miterlimit",
  "fill-rule", "clip-rule", "cx", "cy", "r", "rx", "ry", "x", "y", "x1", "y1", "x2", "y2", "points", "width",
  "height", "transform", "opacity", "fill-opacity", "stroke-opacity",
]);
const ICON_VALUE = /^[A-Za-z0-9 ,.()%#+\-]{0,2000}$/;
const MAX_ICON_BYTES = 4096;
const MAX_ICON_DEPTH = 32;

/** The engine's own icon rule, checked again where the markup is drawn.
 *
 *  The same scanner as lumen-core's `icon_svg_ok` and ingestion's `svg_ok`: the markup is exactly the
 *  canonical form ingestion's cleaner emits — an `<svg>` of `<name attr="value">…</name>` elements,
 *  using only the cleaner's elements, attribute spellings and value characters, with no text,
 *  whitespace, comments or self-closing tags — within the byte and depth caps, and something in it
 *  draws. Anything else is refused at the first deviation. */
export function isSafeIconSvg(markup: string): boolean {
  // A canonical icon is ASCII throughout, so its length here is its length in bytes.
  if (markup.length > MAX_ICON_BYTES || !/^[\x00-\x7f]*$/.test(markup)) return false;
  const run = (start: number, chars: RegExp) => {
    let end = start;
    while (end < markup.length && chars.test(markup[end])) end += 1;
    return markup.slice(start, end);
  };
  const open: string[] = [];
  let at = 0;
  let draws = false;
  for (;;) {
    if (markup[at] !== "<") return false;
    at += 1;
    if (markup[at] === "/") {
      const name = run(at + 1, /[a-z]/);
      at += 1 + name.length;
      if (open.pop() !== name || markup[at] !== ">") return false;
      at += 1;
      if (open.length === 0) return at === markup.length && draws;
      continue;
    }
    const name = run(at, /[a-z]/);
    at += name.length;
    // The root is an `svg`; inside it, any of the cleaner's nine elements.
    const allowed = open.length === 0 ? name === "svg" : name === "svg" || name === "g" || ICON_DRAWING_ELEMENTS.has(name);
    if (!allowed) return false;
    while (markup[at] !== ">") {
      if (markup[at] !== " ") return false;
      const attribute = run(at + 1, /[A-Za-z0-9-]/);
      at += 1 + attribute.length;
      if (!ICON_ATTRIBUTES.has(attribute) || !markup.startsWith('="', at)) return false;
      const close = markup.indexOf('"', at + 2);
      if (close < 0) return false;
      const value = markup.slice(at + 2, close);
      if (!ICON_VALUE.test(value) || value.toLowerCase().includes("url(")) return false;
      at = close + 1;
    }
    at += 1;
    open.push(name);
    if (open.length > MAX_ICON_DEPTH) return false;
    draws ||= ICON_DRAWING_ELEMENTS.has(name);
  }
}

/** A `styles` token, re-checked here too: these values go into generated CSS and markup. */
export function styleOf(brand: BrandData, name: string | null | undefined): StyleValue | undefined {
  const value = resolved(brand, "styles", name);
  if (!value) return undefined;
  switch (value.kind) {
    case "keyword": return typeof value.value === "string" && safeCss(value.value) ? (value as StyleValue) : undefined;
    case "easing": return typeof value.function === "string" && safeCss(value.function) ? (value as StyleValue) : undefined;
    case "transform": return typeof value.value === "string" && /^(none|matrix(3d)?\([0-9 ,.\-e]+\))$/.test(value.value) ? (value as StyleValue) : undefined;
    case "duration": return typeof value.ms === "number" && value.ms >= 0 ? (value as StyleValue) : undefined;
    case "glyph": return typeof value.text === "string" && !/[<>&"']/.test(value.text) ? (value as StyleValue) : undefined;
    case "svg": return typeof value.markup === "string" && isSafeIconSvg(value.markup) ? (value as StyleValue) : undefined;
    case "keyframes":
    case "animation":
    case "reveal":
      return value as StyleValue;
    default:
      return undefined;
  }
}

export function keywordOf(brand: BrandData, name: string | null | undefined): string | undefined {
  const value = styleOf(brand, name);
  return value?.kind === "keyword" ? value.value : undefined;
}

export function durationOf(brand: BrandData, name: string | null | undefined): string | undefined {
  const value = styleOf(brand, name);
  return value?.kind === "duration" ? `${trim(value.ms)}ms` : undefined;
}

export function easingOf(brand: BrandData, name: string | null | undefined): string | undefined {
  const value = styleOf(brand, name);
  return value?.kind === "easing" ? value.function : undefined;
}

export function transformOf(brand: BrandData, name: string | null | undefined): string | undefined {
  const value = styleOf(brand, name);
  return value?.kind === "transform" ? value.value : undefined;
}

export function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrast(a: string, b: string): number {
  const [x, y] = [luminance(a), luminance(b)].sort((m, n) => n - m);
  return (x + 0.05) / (y + 0.05);
}

export const alphaOf = (hex: string) => (hex.length === 9 ? parseInt(hex.slice(7, 9), 16) / 255 : 1);

/** OKLCH chroma of a hex colour, through OKLab. */
export function chroma(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  const a = 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s;
  const bb = 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s;
  return Math.sqrt(a * a + bb * bb);
}

/** A kit size as CSS: exact at the width the kit measured at, shrinking on smaller screens. */
export function fluid(px: number): string {
  const { fixedUpToPx, minShare, measuredAtPx } = FALLBACKS.fluid;
  if (px <= fixedUpToPx) return `${trim(px)}px`;
  const min = Math.max(fixedUpToPx, Math.round(px * minShare));
  return `clamp(${min}px, ${((px / measuredAtPx) * 100).toFixed(3)}vw, ${trim(px)}px)`;
}
