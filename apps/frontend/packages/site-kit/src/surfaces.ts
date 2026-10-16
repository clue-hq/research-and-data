// The brand's surfaces: the kit's nine surface roles, every other `surface.*` token it carries (the
// section backgrounds minted from the seller's site included), the text colour on each, and the
// names the agent and the marketer choose them by (Wave 2 A9; founder Q4 = (b)).
import type { BrandData } from "./brand";
import { chroma, colorOf, contrast, hexOf, luminance, tokenGroups } from "./brand-values";
import { SURFACES as CHOICES, SURFACE_LABELS } from "./schemas";

export const COLOR_ROLES = [
  "text.primary", "text.secondary", "text.muted", "text.inverse", "text.brand", "text.accent",
  "surface.page", "surface.canvas", "surface.card", "surface.muted", "surface.elevated",
  "surface.brand", "surface.brand.subtle", "surface.accent", "surface.inverse",
  "border.subtle", "border.default", "border.strong", "border.brand", "focus.ring",
] as const;

/** The kit's nine surface roles. */
export const SURFACES = [
  "surface.page", "surface.canvas", "surface.card", "surface.muted", "surface.elevated",
  "surface.brand", "surface.brand.subtle", "surface.accent", "surface.inverse",
] as const;

/** Our six choices and the kit role each one is. */
export const CHOICE_ROLE: Record<(typeof CHOICES)[number], string> = {
  page: "surface.page", card: "surface.card", muted: "surface.muted",
  brandSubtle: "surface.brand.subtle", brand: "surface.brand", inverse: "surface.inverse",
};

/** `text.primary` -> `ink-primary`, `surface.brand.subtle` -> `surface-brand-subtle`. */
export function colorVar(role: string): string {
  return role.replace(/^text\./, "ink.").replace(/^border\./, "line.").replace(/^focus\.ring$/, "focus").replace(/\./g, "-");
}

/** Every surface the kit has beyond its nine roles (band surfaces and any other `surface.<x>`). */
export function extraSurfaceRoles(brand: BrandData): string[] {
  const known = new Set<string>(SURFACES);
  return Object.keys(tokenGroups(brand).colors ?? {})
    .filter((role) => role.startsWith("surface.") && !known.has(role) && colorOf(brand, role) !== undefined)
    .sort();
}

/** The nine (those the kit has) and the extras. */
export function surfaceRoles(brand: BrandData): string[] {
  return [...SURFACES.filter((role) => colorOf(brand, role) !== undefined), ...extraSurfaceRoles(brand)];
}

const OUR_ROLES = new Set(Object.values(CHOICE_ROLE));
/** The kit's surfaces beyond our six: canvas, elevated, accent, then the extras. */
export const otherSurfaceRoles = (brand: BrandData) => surfaceRoles(brand).filter((role) => !OUR_ROLES.has(role));

/** The colour role text takes on a surface: the kit's contrast pair when it reads there (4.5:1,
 * WCAG 1.4.3), else the better of text.primary and text.inverse. A pair that does not read is a
 * mis-measured one (S6-1: the capture once took a band's first text, an eyebrow or a card's words);
 * the page must never draw it. A pair whose colours are not hex (oklch) is kept as before. */
export function inkRole(brand: BrandData, surface: string): string | undefined {
  const bg = hexOf(brand, surface);
  if (!bg) return undefined;
  const pairs = (brand.kit as { constraints?: { contrast_pairs?: { background: string; foreground: string }[] } }).constraints?.contrast_pairs ?? [];
  const pair = pairs.find((p) => p.background === surface && hexOf(brand, p.foreground));
  if (pair && contrast(bg.slice(0, 7), hexOf(brand, pair.foreground)!.slice(0, 7)) >= 4.5) return pair.foreground;
  return readableInk(brand, bg);
}

/** The better of text.primary and text.inverse on a colour. */
export function readableInk(brand: BrandData, bg: string): string | undefined {
  const primary = hexOf(brand, "text.primary");
  const inverse = hexOf(brand, "text.inverse");
  if (!primary || !inverse) return primary ? "text.primary" : inverse ? "text.inverse" : undefined;
  return contrast(bg, primary) >= contrast(bg, inverse) ? "text.primary" : "text.inverse";
}

/** A surface is dark when the text on it is lighter than it. */
export function isDarkSurface(brand: BrandData, surface: string): boolean {
  const bg = hexOf(brand, surface);
  const ink = hexOf(brand, inkRole(brand, surface));
  return !!bg && !!ink && luminance(ink) > luminance(bg);
}

export const choiceName = (role: string) => colorVar(role).replace(/^surface-/, "");
const BAND_HEX = /^surface\.band\.[0-9a-f]{6}$/;
const sentence = (words: string[]) => {
  const text = words.filter(Boolean).join(" ");
  return text ? text[0].toUpperCase() + text.slice(1) : text;
};

/** Marketer- and agent-facing names for the kit's other surfaces (rule approved as T-A9-7). */
export function surfaceLabels(brand: BrandData): Map<string, string> {
  const labels = new Map<string, string>();
  const bands = new Map<string, string[]>();
  for (const role of otherSurfaceRoles(brand)) {
    if (BAND_HEX.test(role)) {
      const hex = hexOf(brand, role);
      const kind = isDarkSurface(brand, role) ? "Dark band" : hex && chroma(hex) >= 0.04 ? "Tinted band" : "Light band";
      bands.set(kind, [...(bands.get(kind) ?? []), role]);
      continue;
    }
    const words = role.replace(/^surface\./, "").split(/[.-]/);
    if (words[0] === "band") {
      const rest = words.slice(1);
      const number = /^\d+$/.test(rest[rest.length - 1] ?? "") ? rest.pop() : undefined;
      labels.set(role, `${sentence([...rest, "band"])}${number ? ` ${number}` : ""}`);
    } else {
      labels.set(role, sentence(words));
    }
  }
  for (const [kind, roles] of bands) roles.forEach((role, i) => labels.set(role, roles.length > 1 ? `${kind} ${i + 1}` : kind));
  return labels;
}

export type SurfaceChoice = { value: string; label: string; role: string };

/** Every surface a section may stand on: our six as today, then the kit's others. */
export function surfaceChoices(brand: BrandData): SurfaceChoice[] {
  const labels = surfaceLabels(brand);
  return [
    ...CHOICES.map((value) => ({ value: value as string, label: SURFACE_LABELS[value], role: CHOICE_ROLE[value] })),
    ...otherSurfaceRoles(brand).map((role) => ({ value: choiceName(role), label: labels.get(role) ?? role, role })),
  ];
}

export const surfaceRoleOf = (brand: BrandData, choice: string) => surfaceChoices(brand).find((c) => c.value === choice)?.role;
