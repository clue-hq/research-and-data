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
        ? `oklch(${value.l} ${value.c} ${value.h} / ${value.alpha ?? 1})`
        : null;
    case "alias":
      return typeof value.token === "string"
        ? resolveColorToken(value.token, colors, seen)
        : null;
    default:
      return null;
  }
}

/** A token string as carried on a `Paint`/`Color` (`paint.token` /
 * `color.token`) may or may not include the `$` prefix used in author-facing
 * hints (e.g. `fill($surface.page)`); this strips it before lookup so both
 * forms hit the same map entry. */
export function resolveTokenColor(map: TokenColorMap, token: string): string | null {
  const name = token.startsWith("$") ? token.slice(1) : token;
  return map[name] ?? null;
}
