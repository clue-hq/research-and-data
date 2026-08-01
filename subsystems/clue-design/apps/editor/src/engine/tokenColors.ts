/**
 * Resolves brand-kit color tokens (`fill($surface.page)` etc.) to real CSS
 * color strings, for the canvas paint path. The renderer previously had no
 * source of truth for token values at all — `tokenFallback` in
 * `renderAdapter.ts` is a 4-bucket string heuristic ("surface" -> one cream,
 * always) that stays correct only for the *absence* of real data. This
 * module is that real data source.
 *
 * Input shape mirrors the server's raw brand-kit JSON (`GET
 * /brand-kits/{id}` -> `brand_kit_json`), specifically the `tokens.colors`
 * catalog: each entry is `{ value: { default: ColorTokenValue, modes }, ... }`
 * where `ColorTokenValue` is a Rust-side tagged union (`crates/lumen-core/src
 * /brand.rs` `ColorTokenValue`): `{kind:"hex",value}` |
 * `{kind:"oklch",l,c,h,alpha}` | `{kind:"alias",token}`. Only `default` is
 * read here — the canvas preview doesn't do mode selection (light/dark/etc),
 * matching how `Color` in `contracts.ts` has no mode concept either.
 *
 * A brand kit's `tokens.aliases` map (legacy/alternate names -> a real color
 * token) is folded in after direct colors resolve, so an alias chain like
 * `brand.primary` -> `surface.brand` -> hex resolves the same as a
 * same-catalog `{kind:"alias"}` chain.
 */

export interface ColorTokenValuePayload {
  kind?: string;
  value?: string;
  l?: number;
  c?: number;
  h?: number;
  alpha?: number;
  token?: string;
}

export interface ColorTokenPayload {
  value?: {
    default?: ColorTokenValuePayload;
  };
}

export interface TokenAliasPayload {
  token?: string;
}

export interface BrandKitTokensPayload {
  colors?: Record<string, ColorTokenPayload>;
  aliases?: Record<string, TokenAliasPayload>;
}

/** The slice of the raw brand-kit JSON this module needs. Deliberately
 * loose (all-optional) — it mirrors an external payload we don't own. */
export interface BrandKitDetailPayload {
  tokens?: BrandKitTokensPayload;
}

/** Token name -> resolved CSS color string. Built once per attached kit. */
export type TokenColorMap = Record<string, string>;

/**
 * The platform fallback kit's id (`crates/lumen-core/fixtures/brand_kits
 * /platform_default.json`, served by the API at `GET
 * /brand-kits/brand_kit_platform_default`). Canvas token resolution falls
 * back to this kit's values when the document has no attached brand kit —
 * mirroring what server-side token resolution/export already does
 * (`ensure_platform_color_tokens` in `crates/lumen-core/src/brand.rs`
 * backfills the full color set onto this kit at load time), so the canvas
 * and the server-authoritative export agree instead of diverging.
 */
export const PLATFORM_DEFAULT_BRAND_KIT_ID = "brand_kit_platform_default";

const MAX_ALIAS_HOPS = 8;

/**
 * Builds a flat token-name -> CSS-color map from a raw brand-kit detail
 * payload. Resolves `{kind:"alias"}` chains (both within `tokens.colors` and
 * via the separate `tokens.aliases` map) with a cycle guard: a chain longer
 * than `MAX_ALIAS_HOPS`, or one that revisits a token, stops and drops that
 * entry rather than looping forever on a malformed kit.
 *
 * `null`/missing input (no kit attached, fetch failed) yields an empty map —
 * every lookup then misses and callers fall through to the string heuristic.
 */
export function buildTokenColorMap(kit: BrandKitDetailPayload | null | undefined): TokenColorMap {
  const colors = kit?.tokens?.colors ?? {};
  const aliases = kit?.tokens?.aliases ?? {};
  const map: TokenColorMap = {};

  for (const name of Object.keys(colors)) {
    const resolved = resolveColorToken(name, colors, new Set());
    if (resolved) {
      map[name] = resolved;
    }
  }

  for (const [aliasName, alias] of Object.entries(aliases)) {
    const target = alias?.token;
    if (!target) {
      continue;
    }
    if (map[target]) {
      map[aliasName] = map[target];
      continue;
    }
    // The alias target may itself be resolvable directly from `colors` even
    // if it didn't land in `map` (e.g. iteration order) — try once more.
    const resolved = resolveColorToken(target, colors, new Set());
    if (resolved) {
      map[aliasName] = resolved;
    }
  }

  return map;
}

function resolveColorToken(
  name: string,
  colors: Record<string, ColorTokenPayload>,
  seen: Set<string>
): string | null {
  if (seen.has(name) || seen.size >= MAX_ALIAS_HOPS) {
    return null;
  }
  seen.add(name);

  const value = colors[name]?.value?.default;
  if (!value) {
    return null;
  }

  switch (value.kind) {
    case "hex":
      return typeof value.value === "string" ? value.value : null;
    case "oklch":
      return typeof value.l === "number" &&
        typeof value.c === "number" &&
        typeof value.h === "number"
        ? oklchToHexCss(value.l, value.c, value.h, value.alpha ?? 1)
        : null;
    case "alias":
      return typeof value.token === "string"
        ? resolveColorToken(value.token, colors, seen)
        : null;
    default:
      return null;
  }
}

/**
 * oklch -> sRGB hex, so the token map only ever holds strings BOTH canvas
 * backends can paint. The CanvasKit paint path (`parseColor` in
 * `canvaskit/drawDescriptors.ts`) parses hex and rgb()/rgba() only — an
 * `oklch(...)` string returns null there, which erased kit-valued fills
 * (transparent) and dropped text to black on the product canvas: exactly the
 * K0 live-proof failure, because ingested kits express their palette ramps
 * in oklch and every semantic token aliases into one. Matches the engine's
 * own resolution (`crates/lumen-core` oklch -> hex, e.g. the Insight kit's
 * `surface.brand` -> #00525C), so canvas, export, and agent preview agree.
 *
 * Standard OKLab math (Björn Ottosson's reference matrices): oklch -> OKLab
 * -> LMS' -> cube -> linear sRGB -> gamma-encode, channels clamped to [0,1]
 * (out-of-gamut values clip, same as the engine). Alpha < 1 emits 8-digit
 * hex, which `parseColor` already handles.
 */
export function oklchToHexCss(l: number, c: number, h: number, alpha = 1): string {
  const hRad = (h * Math.PI) / 180;
  const labA = c * Math.cos(hRad);
  const labB = c * Math.sin(hRad);

  const lPrime = l + 0.3963377774 * labA + 0.2158037573 * labB;
  const mPrime = l - 0.1055613458 * labA - 0.0638541728 * labB;
  const sPrime = l - 0.0894841775 * labA - 1.291485548 * labB;

  const l3 = lPrime * lPrime * lPrime;
  const m3 = mPrime * mPrime * mPrime;
  const s3 = sPrime * sPrime * sPrime;

  const red = 4.0767416621 * l3 - 3.3077115913 * m3 + 0.2309699292 * s3;
  const green = -1.2684380046 * l3 + 2.6097574011 * m3 - 0.3413193965 * s3;
  const blue = -0.0041960863 * l3 - 0.7034186147 * m3 + 1.707614701 * s3;

  const channel = (linear: number): string => {
    const clamped = Math.min(1, Math.max(0, linear));
    const encoded =
      clamped <= 0.0031308 ? clamped * 12.92 : 1.055 * Math.pow(clamped, 1 / 2.4) - 0.055;
    return Math.round(encoded * 255)
      .toString(16)
      .padStart(2, "0");
  };

  const hex = `#${channel(red)}${channel(green)}${channel(blue)}`;
  if (alpha >= 1) {
    return hex;
  }
  const alphaHex = Math.round(Math.min(1, Math.max(0, alpha)) * 255)
    .toString(16)
    .padStart(2, "0");
  return `${hex}${alphaHex}`;
}

/** A token string as carried on a `Paint`/`Color` (`paint.token` /
 * `color.token`) may or may not include the `$` prefix used in author-facing
 * hints (e.g. `fill($surface.page)`); this strips it before lookup so both
 * forms hit the same map entry. */
export function resolveTokenColor(map: TokenColorMap, token: string): string | null {
  const name = token.startsWith("$") ? token.slice(1) : token;
  return map[name] ?? null;
}

// ---------------------------------------------------------------------------
// K1.5 ("K0.5 for type"): typography + number tokens, resolved client-side.
//
// Agent proposal ops insert SKELETON text (Inter 16) carrying a style_token;
// the server resolves the real family/size only at post-accept preflight. The
// editor measured the skeleton (~17px/line), relayout used those metrics, and
// the accept-time freeze baked the collapsed POSITIONS — the LUMV0903/0810
// ghost. Resolving the kit's typography roles into the client measure/render
// path measures the true 80pt headline before anything freezes, and makes
// canvas type WYSIWYG. Radius / stroke-width / opacity number tokens ride
// the same map so their fallback diagnostics can clear too.
// ---------------------------------------------------------------------------

/** Mirrors the engine's ResolvedTypographyStyle (brand.rs resolve_text_style):
 * what a `style($type.role)` supplies to a text node. All fields optional —
 * apply over the node's literals only when present. */
export interface TokenTextStyle {
  fontFamily?: string;
  fontSize?: number;
  fontWeight?: number;
  lineHeight?: number;
  letterSpacing?: number;
}

export type TokenTextStyleMap = Record<string, TokenTextStyle>;
export type TokenNumberMap = Record<string, number>;

export interface KitTokenMaps {
  colors: TokenColorMap;
  typography: TokenTextStyleMap;
  numbers: TokenNumberMap;
}

interface TypographyValuePayload {
  kind?: string;
  font_family?: unknown;
  font_size?: unknown;
  font_weight?: unknown;
  line_height?: unknown;
  letter_spacing?: unknown;
  token?: unknown;
}

interface NumberValuePayload {
  kind?: string;
  value?: unknown;
}

interface KitTokensPayload extends BrandKitTokensPayload {
  typography?: Record<string, { value?: { default?: TypographyValuePayload } }>;
  numbers?: Record<string, { value?: { default?: NumberValuePayload } }>;
  spacing?: Record<string, { value?: { default?: NumberValuePayload } }>;
  radii?: Record<string, { value?: { default?: NumberValuePayload } }>;
  stroke_widths?: Record<string, { value?: { default?: NumberValuePayload } }>;
  opacity?: Record<string, { value?: { default?: NumberValuePayload } }>;
}

/** All three client-resolvable maps from one kit detail payload. */
export function buildKitTokenMaps(kit: BrandKitDetailPayload | null | undefined): KitTokenMaps {
  const tokens = (kit?.tokens ?? {}) as KitTokensPayload;

  const typography: TokenTextStyleMap = {};
  for (const [role, entry] of Object.entries(tokens.typography ?? {})) {
    const value = entry?.value?.default;
    if (!value || (value.kind && value.kind !== "style")) {
      // Alias roles are rare and server-resolved; skip rather than chase.
      continue;
    }
    const style: TokenTextStyle = {};
    if (typeof value.font_family === "string") style.fontFamily = value.font_family;
    if (typeof value.font_size === "number") style.fontSize = value.font_size;
    if (typeof value.font_weight === "number") style.fontWeight = value.font_weight;
    if (typeof value.line_height === "number") style.lineHeight = value.line_height;
    if (typeof value.letter_spacing === "number") style.letterSpacing = value.letter_spacing;
    if (Object.keys(style).length > 0) {
      typography[role] = style;
    }
  }

  const numbers: TokenNumberMap = {};
  for (const category of ["numbers", "spacing", "radii", "stroke_widths", "opacity"] as const) {
    for (const [name, entry] of Object.entries(tokens[category] ?? {})) {
      const value = entry?.value?.default;
      if (value && typeof value.value === "number") {
        numbers[name] = value.value;
      }
    }
  }

  return { colors: buildTokenColorMap(kit), typography, numbers };
}
