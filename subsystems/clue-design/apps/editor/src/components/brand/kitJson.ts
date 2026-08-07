/**
 * Small readers over the raw brand-kit JSON + ingestion summary shapes.
 *
 * The kit JSON is intentionally typed `any` at the boundary (the engine owns
 * its schema; the review page only displays it), so these helpers do the
 * defensive plucking in one place rather than sprinkling `?.` chains through
 * every section component. Nothing here mutates.
 */

export interface ColorToken {
  token: string;
  role: string;
  value: string;
  darkValue: string | null;
  pointer: string | null;
  basis: string | null;
}

export interface FontFace {
  weight: number | string | null;
  style: string | null;
  sourceUrl: string | null;
}

export interface FontEntry {
  key: string;
  family: string;
  fallbackStack: string[];
  faces: FontFace[];
}

export interface TypographyRow {
  role: string;
  family: string;
  size: number | null;
  weight: number | string | null;
  lineHeight: number | string | null;
}

export interface LogoVariant {
  name: string;
  colorMode: string | null;
  assetId: string | null;
}

export interface LogoGroup {
  key: string;
  usage: string;
  variants: LogoVariant[];
}

export interface ImageEntry {
  key: string;
  assetId: string | null;
  role: string | null;
  title: string | null;
  description: string | null;
}

export interface RoleAssignment {
  token: string;
  value: string | null;
  basis: string | null;
  pointer: string | null;
}

export interface IngestionRule {
  kind: string;
  text: string;
}

function asObject(value: unknown): Record<string, any> {
  return value && typeof value === "object" ? (value as Record<string, any>) : {};
}

/** Resolve a color token's default + dark values from the kit JSON
 * `tokens.colors.{token}.value.{default,modes["theme.dark"]}`. */
export function readColorTokens(kitJson: any): ColorToken[] {
  const colors = asObject(asObject(kitJson.tokens).colors);
  return Object.entries(colors).map(([token, raw]) => {
    const entry = asObject(raw);
    const value = asObject(entry.value);
    const def = asObject(value.default);
    const dark = asObject(asObject(value.modes)["theme.dark"]);
    return {
      token,
      role: typeof entry.role === "string" ? entry.role : "",
      value: typeof def.value === "string" ? def.value : "",
      darkValue: typeof dark.value === "string" ? dark.value : null,
      pointer:
        typeof asObject(entry.provenance).source === "string"
          ? asObject(entry.provenance).source
          : null,
      basis: null
    };
  });
}

/** Semantic display order — alphabetical scatters the story (accent before
 * page); a reviewer reads surfaces base→brand, text primary→accent. Unknown
 * tokens sort after the known ones, alphabetically. */
const ROLE_ORDER = [
  "surface.page",
  "surface.canvas",
  "surface.card",
  "surface.elevated",
  "surface.muted",
  "surface.brand",
  "surface.brand.subtle",
  "surface.accent",
  "surface.inverse",
  "text.primary",
  "text.secondary",
  "text.muted",
  "text.inverse",
  "text.brand",
  "text.accent",
  "focus.ring",
  "border.subtle",
  "border.default",
  "border.strong",
  "border.brand"
];

function semanticSort(tokens: ColorToken[]): ColorToken[] {
  return [...tokens].sort((a, b) => {
    const ai = ROLE_ORDER.indexOf(a.token);
    const bi = ROLE_ORDER.indexOf(b.token);
    if (ai !== -1 && bi !== -1) return ai - bi;
    if (ai !== -1) return -1;
    if (bi !== -1) return 1;
    return a.token.localeCompare(b.token);
  });
}

/** Group color tokens by the role families the review page shows side by side. */
export function groupColorsByRole(tokens: ColorToken[]): {
  backgrounds: ColorToken[];
  text: ColorToken[];
  accent: ColorToken[];
  borders: ColorToken[];
} {
  const backgrounds: ColorToken[] = [];
  const text: ColorToken[] = [];
  const accent: ColorToken[] = [];
  const borders: ColorToken[] = [];
  for (const token of semanticSort(tokens)) {
    if (token.token.startsWith("palette.")) continue; // palettes render as ramps
    if (token.role === "surface" || token.token.startsWith("surface.")) backgrounds.push(token);
    else if (token.role === "text" || token.token.startsWith("text.")) text.push(token);
    else if (token.role === "border" || token.token.startsWith("border.")) borders.push(token);
    else accent.push(token);
  }
  return { backgrounds, text, accent, borders };
}

/** Up to eight signature hexes for a kit's list-card palette strip: the brand
 * story first (brand, accent, page, ink), then named extras. */
export function signatureColors(kitJson: any): string[] {
  const tokens = readColorTokens(kitJson);
  const byToken = new Map(tokens.map((token) => [token.token, token.value]));
  const picks: string[] = [];
  const push = (hex: string | null | undefined) => {
    if (hex && !picks.includes(hex)) picks.push(hex);
  };
  push(byToken.get("surface.brand"));
  push(byToken.get("surface.accent"));
  push(byToken.get("text.primary"));
  push(byToken.get("surface.page"));
  for (const token of tokens) {
    if (token.token.startsWith("palette.extra.")) push(token.value);
  }
  return picks.slice(0, 8);
}

/** Palette ramps (primary/neutral) sorted by numeric stop, plus the flat extras. */
export function readPaletteRamps(tokens: ColorToken[]): {
  primary: ColorToken[];
  neutral: ColorToken[];
  extras: ColorToken[];
} {
  const byStop = (a: ColorToken, b: ColorToken) => stopOf(a.token) - stopOf(b.token);
  return {
    primary: tokens.filter((t) => t.token.startsWith("palette.primary.")).sort(byStop),
    neutral: tokens.filter((t) => t.token.startsWith("palette.neutral.")).sort(byStop),
    extras: tokens.filter((t) => t.token.startsWith("palette.extra."))
  };
}

function stopOf(token: string): number {
  const parts = token.split(".");
  const stop = Number(parts[parts.length - 1]);
  return Number.isFinite(stop) ? stop : 0;
}

export function readFonts(kitJson: any): FontEntry[] {
  const fonts = asObject(asObject(asObject(kitJson).assets).fonts);
  return Object.entries(fonts).map(([key, raw]) => {
    const entry = asObject(raw);
    const faces = Array.isArray(entry.faces) ? entry.faces : [];
    return {
      key,
      family: typeof entry.family === "string" ? entry.family : key,
      fallbackStack: Array.isArray(entry.fallback_stack)
        ? entry.fallback_stack.filter((f: unknown): f is string => typeof f === "string")
        : [],
      faces: faces.map((face: any) => ({
        weight: face?.weight ?? null,
        style: typeof face?.style === "string" ? face.style : null,
        sourceUrl: typeof face?.source_url === "string" ? face.source_url : null
      }))
    };
  });
}

export function fontSpecimenStack(font: FontEntry): string {
  return [font.family, ...font.fallbackStack].filter(Boolean).join(", ") || "inherit";
}

export function readTypographyRamp(kitJson: any): TypographyRow[] {
  const typography = asObject(asObject(kitJson.tokens).typography);
  return Object.entries(typography).map(([, raw]) => {
    const entry = asObject(raw);
    const def = asObject(asObject(entry.value).default);
    return {
      role: typeof entry.role === "string" ? entry.role : "",
      family: typeof def.font_family === "string" ? def.font_family : "",
      size: typeof def.font_size === "number" ? def.font_size : null,
      weight: def.font_weight ?? null,
      lineHeight: def.line_height ?? null
    };
  });
}

export function readLogos(kitJson: any): LogoGroup[] {
  const logos = asObject(asObject(asObject(kitJson).assets).logos);
  return Object.entries(logos).map(([key, raw]) => {
    const entry = asObject(raw);
    const variants = Array.isArray(entry.variants) ? entry.variants : [];
    return {
      key,
      usage: typeof entry.usage === "string" ? entry.usage : key,
      variants: variants.map((variant: any) => ({
        name: typeof variant?.name === "string" ? variant.name : "",
        colorMode: typeof variant?.color_mode === "string" ? variant.color_mode : null,
        assetId: typeof variant?.asset_id === "string" ? variant.asset_id : null
      }))
    };
  });
}

/** A reversed logo variant needs a dark backdrop behind its thumb. */
export function isReversedVariant(variant: LogoVariant): boolean {
  const mode = (variant.colorMode ?? "").toLowerCase();
  const name = (variant.name ?? "").toLowerCase();
  return mode.includes("reversed") || mode.includes("inverse") || name.includes("reversed");
}

export function readImages(kitJson: any): ImageEntry[] {
  const images = asObject(asObject(asObject(kitJson).assets).images);
  return Object.entries(images).map(([key, raw]) => {
    const entry = asObject(raw);
    return {
      key,
      assetId: typeof entry.asset_id === "string" ? entry.asset_id : null,
      role: typeof entry.role === "string" ? entry.role : null,
      title: typeof entry.title === "string" ? entry.title : null,
      description: typeof entry.description === "string" ? entry.description : null
    };
  });
}

/** The ingestion report lives under `brand_summary.ingestion`. */
export function readIngestionReport(summary: any): Record<string, any> | null {
  const report = asObject(summary).ingestion;
  return report && typeof report === "object" ? (report as Record<string, any>) : null;
}

export function readRoleAssignments(report: Record<string, any> | null): RoleAssignment[] {
  const rows = report && Array.isArray(report.role_assignments) ? report.role_assignments : [];
  return rows.map((row: any) => ({
    token: typeof row?.token === "string" ? row.token : "",
    value: typeof row?.value === "string" ? row.value : null,
    basis: typeof row?.basis === "string" ? row.basis : null,
    pointer: typeof row?.pointer === "string" ? row.pointer : null
  }));
}

export function readIngestionRules(report: Record<string, any> | null): IngestionRule[] {
  const rules = report && Array.isArray(report.rules) ? report.rules : [];
  return rules.map((rule: any) => ({
    kind: typeof rule?.kind === "string" ? rule.kind : "rule",
    text: typeof rule?.text === "string" ? rule.text : ""
  }));
}

export function readStringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}
