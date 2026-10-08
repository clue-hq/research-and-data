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

export const SURFACES = [
  "surface.page", "surface.canvas", "surface.card", "surface.muted", "surface.elevated",
  "surface.brand", "surface.brand.subtle", "surface.accent", "surface.inverse",
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

function luminance(hex: string): number {
  const h = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => {
    const c = parseInt(h.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [x, y] = [luminance(a), luminance(b)].sort((m, n) => n - m);
  return (x + 0.05) / (y + 0.05);
}

function isLight(rgb: string): boolean {
  const m = rgb.match(/\d+(\.\d+)?/g);
  if (!m) return false;
  const [r, g, b] = m.slice(0, 3).map(Number);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 200;
}

/** Text colour role for each surface: the kit's own contrast pair first, else the better of
 * text.primary and text.inverse by contrast ratio. */
function onSurface(brand: BrandData): Record<string, string> {
  const colors = tokens(brand, "colors");
  const hex = (role: string) => colors[role]?.value.default.value as string | undefined;
  const pairs = ((brand.kit as { constraints?: { contrast_pairs?: { background: string; foreground: string }[] } })
    .constraints?.contrast_pairs ?? []);
  const out: Record<string, string> = {};
  for (const surface of SURFACES) {
    const bg = hex(surface);
    if (!bg) continue;
    const pair = pairs.find((p) => p.background === surface);
    if (pair && hex(pair.foreground)) {
      out[surface] = pair.foreground;
      continue;
    }
    const primary = hex("text.primary") ?? "#111111";
    const inverse = hex("text.inverse") ?? "#ffffff";
    out[surface] = contrast(bg, primary) >= contrast(bg, inverse) ? "text.primary" : "text.inverse";
  }
  return out;
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

  for (const [surface, ink] of Object.entries(onSurface(brand))) {
    vars.push(`--brand-on-${colorVar(surface)}:var(--brand-${colorVar(ink)})`);
  }

  // The primary button, measured from the brand's own hero clone. A white measured button is
  // the "on photo" variant, so the solid button falls back to the brand surface with its pair.
  const button = brand.measured?.primary_button;
  if (button) {
    const light = isLight(button.background);
    vars.push(
      `--brand-button-bg:${light ? "var(--brand-surface-brand)" : button.background}`,
      `--brand-button-fg:${light ? "var(--brand-on-surface-brand)" : button.color}`,
      `--brand-button-light-bg:#ffffff`,
      `--brand-button-light-fg:${light ? button.color : button.background}`,
      `--brand-button-radius:${button.borderRadius}`,
      `--brand-button-px:${button.paddingX}`,
      `--brand-button-height:${button.height}`,
      `--brand-button-font:${button.fontFamily}`,
      `--brand-button-size:${button.fontSize}`,
      `--brand-button-weight:${button.fontWeight}`,
    );
  } else {
    // No solid button in the captured sections: the kit's own (brand colour fill with its pair,
    // a pill, the cta type role).
    const cta = typeVar("cta");
    vars.push(
      "--brand-button-bg:var(--brand-surface-brand)",
      "--brand-button-fg:var(--brand-on-surface-brand,#ffffff)",
      "--brand-button-light-bg:#ffffff",
      "--brand-button-light-fg:var(--brand-surface-brand)",
      "--brand-button-radius:var(--brand-radius-full,9999px)",
      "--brand-button-px:1.25em",
      "--brand-button-height:2.75rem",
      `--brand-button-font:var(--brand-font-${cta},inherit)`,
      `--brand-button-size:var(--brand-text-${cta},1rem)`,
      `--brand-button-weight:var(--brand-text-${cta}-weight,600)`,
    );
  }

  // Heading ink on light surfaces, measured from the clones (kits often record it as unmapped).
  const headingInk = brand.measured?.heading_on_light?.color;
  vars.push(`--brand-heading-ink:${headingInk ?? "var(--brand-ink-primary)"}`);

  lines.push(`.brand-root{${vars.join(";")}}`);
  // Light vs dark is decided per brand from the surface's own colour (Conduit's brand surface is a
  // light cyan, Garner's a dark green): headings take the measured ink on light surfaces, and
  // buttons switch to the light variant on dark ones.
  const surfaceHex = tokens(brand, "colors");
  const lightness = (role: string) => {
    const hex = surfaceHex[role]?.value.default.value as string | undefined;
    return hex ? luminance(hex) : 1;
  };
  const cls = (role: string) => `.bg-${colorVar(role)}`;
  const light = SURFACES.filter((s) => lightness(s) > 0.35).map(cls);
  const dark = SURFACES.filter((s) => lightness(s) <= 0.35).map(cls);
  // The nearest surface decides: each surface sets the heading colour as an inherited variable, so
  // a dark card inside a light section gets light headings (a descendant rule matched through the
  // nesting and put the brand's dark heading ink on black).
  if (light.length) lines.push(`:is(${light.join(",")}){--brand-heading-color:var(--brand-heading-ink)}`);
  if (dark.length) lines.push(`:is(${dark.join(",")}){--brand-heading-color:currentColor}`);
  lines.push(".brand-heading{color:var(--brand-heading-color,currentColor)}");
  if (dark.length) {
    lines.push(
      `@layer components{:is(${dark.join(",")}) .brand-btn{background:var(--brand-button-light-bg);color:var(--brand-button-light-fg)}}`,
    );
  }
  // Component rules live in the components layer so Tailwind utilities (hidden, sm:inline-flex…)
  // can still override them, as they would any component class.
  lines.push(
    "@layer components{" +
      ".brand-btn{display:inline-flex;align-items:center;gap:.5em;min-height:var(--brand-button-height);" +
      "padding:0 var(--brand-button-px);border-radius:var(--brand-button-radius);" +
      "font-family:var(--brand-button-font);font-size:var(--brand-button-size);" +
      "font-weight:var(--brand-button-weight);background:var(--brand-button-bg);" +
      "color:var(--brand-button-fg);text-decoration:none;white-space:nowrap}" +
      ".brand-btn-light{background:var(--brand-button-light-bg);color:var(--brand-button-light-fg)}" +
      "}",
  );
  return lines.join("\n");
}
