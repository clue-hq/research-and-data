// Brand kit -> one theme stylesheet (spike version of the A5 seller-theme generator).
//
// Per-brand values are emitted at runtime as `--brand-*` custom properties on `.brand-root`.
// globals.css maps them once into Tailwind v4 theme variables (`@theme inline`), so every
// section uses fixed class names (`text-headline`, `bg-surface-brand`, `rounded-card`) and the
// brand decides the values. Clones are untouched: they carry their own captured CSS.
import type { BrandData } from "./brands";

type Token = { value: { default: Record<string, unknown> } };

export const COLOR_ROLES = [
  "text.primary", "text.secondary", "text.muted", "text.inverse", "text.brand", "text.accent",
  "surface.page", "surface.canvas", "surface.card", "surface.muted", "surface.elevated",
  "surface.brand", "surface.brand.subtle", "surface.accent", "surface.inverse",
  "border.subtle", "border.default", "border.strong", "border.brand", "focus.ring",
] as const;

export const TYPE_ROLES = [
  "display", "headline", "title", "subtitle", "body", "body.small",
  "eyebrow", "cta", "stat", "label", "caption", "legal",
] as const;

export const RADIUS_ROLES = ["none", "xs", "sm", "md", "lg", "xl", "card", "button", "badge", "full"] as const;

/** `text.primary` -> `ink-primary`, `surface.brand.subtle` -> `surface-brand-subtle`. */
export function colorVar(role: string): string {
  return role
    .replace(/^text\./, "ink.")
    .replace(/^border\./, "line.")
    .replace(/^focus\.ring$/, "focus")
    .replace(/\./g, "-");
}

export const typeVar = (role: string) => role.replace(/\./g, "-");

function tokens(brand: BrandData, group: string): Record<string, Token> {
  const all = (brand.kit as { tokens: Record<string, Record<string, Token>> }).tokens;
  return all[group] ?? {};
}

function fluid(px: number): string {
  // Exact at 1440px wide (the size the kit measured); scales down on smaller screens.
  if (px <= 24) return `${px}px`;
  const min = Math.max(24, Math.round(px * 0.5));
  return `clamp(${min}px, ${(px / 14.4).toFixed(3)}vw, ${px}px)`;
}

function family(name: string, asset: string): string {
  const fallback = asset === "brand" ? "Georgia, serif" : "system-ui, sans-serif";
  return `"${name}", ${fallback}`;
}

export function themeCss(brand: BrandData): string {
  const lines: string[] = [];

  for (const face of brand.fonts) {
    lines.push(
      `@font-face{font-family:"${face.family}";src:url("${face.file}");` +
        `font-weight:${face.weight ?? 400};font-style:${face.style};font-display:swap}`,
    );
  }

  const vars: string[] = [];
  const colors = tokens(brand, "colors");
  for (const role of COLOR_ROLES) {
    const value = colors[role]?.value.default.value;
    if (typeof value === "string") vars.push(`--brand-${colorVar(role)}:${value}`);
  }

  const type = tokens(brand, "typography");
  for (const role of TYPE_ROLES) {
    const style = type[`type.${role}`]?.value.default as
      | { font_size: number; font_family: string; font_asset: string; font_weight: number;
          line_height: number; letter_spacing: number }
      | undefined;
    if (!style) continue;
    const name = typeVar(role);
    vars.push(
      `--brand-font-${name}:${family(style.font_family, style.font_asset)}`,
      `--brand-text-${name}:${fluid(style.font_size)}`,
      `--brand-text-${name}-lh:${style.line_height}`,
      `--brand-text-${name}-weight:${style.font_weight}`,
      `--brand-text-${name}-tracking:${style.letter_spacing}em`,
    );
  }

  const radii = tokens(brand, "radii");
  for (const role of RADIUS_ROLES) {
    const value = radii[`radius.${role}`]?.value.default.value;
    if (typeof value === "number") vars.push(`--brand-radius-${role}:${value}px`);
  }

  lines.push(`.brand-root{${vars.join(";")}}`);
  return lines.join("\n");
}
