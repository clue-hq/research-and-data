import type { z } from "zod";
import type {
  BrandColorGroupSchema,
  BrandColorSwatchSchema,
} from "./brand-context";
import type {
  BrandContextWorkspace,
  BrandTextStyle,
  BrandTypeface,
} from "./brand-context";
import type {
  BrandColorToken,
  BrandFontAsset,
  BrandKitDetail,
  BrandTypographyToken,
} from "./brand-kit";

/**
 * Slice 1: the pure kit → page mapping (plan §5). No transport lives here —
 * the repository fetches, this module decides what the page shows.
 *
 * Two rules govern every decision below:
 *  1. **Honest empties.** A section the kit does not carry renders its
 *     designed empty state. Nothing is invented to fill a panel.
 *  2. **Never blank the page for one bad row.** An unresolvable token or
 *     asset drops itself, not its neighbours.
 */

// The lifted model exports these two as schemas only; inferring them here
// keeps that file byte-untouched.
type BrandColorGroup = z.infer<typeof BrandColorGroupSchema>;
type BrandColorSwatch = z.infer<typeof BrandColorSwatchSchema>;

/** The mode selector the ingestion emitter writes its dark colorway under. */
const DARK_MODE_SELECTOR = "theme.dark";

/** Alias chains are bounded; a cycle resolves to "unresolvable", not a hang. */
const MAX_ALIAS_DEPTH = 8;

const SEMANTIC_GROUP_ID = "semantic";

/**
 * The workspace a client sees when the transport is live but there is nothing
 * to show — no kit yet, or the read failed. Every section is its designed
 * empty state; fixture content would lie to a real client.
 */
export function emptyBrandContextWorkspace(): BrandContextWorkspace {
  return {
    assets: [],
    colorGroups: [],
    id: "brand-context",
    knowledgeFolders: [],
    name: "",
    textStyles: [],
    typefaces: [],
  };
}

export function toBrandContextWorkspace(
  kit: BrandKitDetail,
): BrandContextWorkspace {
  const json = kit.brand_kit_json;
  return {
    assets: [],
    colorGroups: toColorGroups(json.tokens?.colors),
    id: kit.brand_kit.id,
    // Brand knowledge documents have no form in the kit (`constraints.tone` is
    // a word list, not markdown) — honest empty in v1, recorded as future work
    // in `docs/api-contracts/brand-context.md`.
    knowledgeFolders: [],
    name: kit.brand_kit.name,
    textStyles: toTextStyles(json.tokens?.typography),
    typefaces: toTypefaces(json.assets?.fonts),
  };
}

type ColorTokens = Readonly<Record<string, BrandColorToken | null>>;

/**
 * The kit's colour catalog, grouped the way the screen reads it: every
 * semantic role in one group, then one group per `palette.<family>.*` ramp.
 */
function toColorGroups(colors: ColorTokens | undefined): BrandColorGroup[] {
  if (!colors) return [];
  const groups = new Map<string, BrandColorGroup>();

  for (const path of Object.keys(colors).sort(compareColorPaths)) {
    if (!colors[path]) continue;
    const lightValue = resolveColor(colors, path, "light", 0);
    if (!lightValue) continue;
    const family = paletteFamily(path);
    const groupId = family ? `palette-${family}` : SEMANTIC_GROUP_ID;
    const group = groups.get(groupId) ?? {
      id: groupId,
      label: family ? `${titleCase(family)} palette` : "Semantic roles",
      swatches: [] as BrandColorSwatch[],
    };
    group.swatches.push({
      id: path,
      label: family ? (lastSegment(path) ?? path) : path,
      lightValue,
      // No dark colorway in the kit means the light value IS what dark shows.
      // Synthesizing one here would fabricate brand colour.
      darkValue: resolveColor(colors, path, "dark", 0) ?? lightValue,
    });
    groups.set(groupId, group);
  }

  const ordered = [...groups.values()];
  ordered.sort((left, right) => {
    if (left.id === SEMANTIC_GROUP_ID) return -1;
    if (right.id === SEMANTIC_GROUP_ID) return 1;
    return left.id.localeCompare(right.id);
  });
  return ordered;
}

function resolveColor(
  colors: ColorTokens,
  path: string,
  mode: "light" | "dark",
  depth: number,
): string | null {
  if (depth > MAX_ALIAS_DEPTH) return null;
  const token = colors[path];
  if (!token) return null;
  const value =
    (mode === "dark" ? token.value.modes?.[DARK_MODE_SELECTOR] : undefined) ??
    token.value.default;

  if (value.kind === "hex") return value.value;
  if (value.kind === "oklch") {
    const base = `oklch(${value.l} ${value.c} ${value.h}`;
    return value.alpha != null && value.alpha < 1
      ? `${base} / ${value.alpha})`
      : `${base})`;
  }
  return resolveColor(colors, value.token, mode, depth + 1);
}

type FontAssets = Readonly<Record<string, BrandFontAsset | null>>;

/**
 * `assets.fonts` → the typeface list. The dummy's two-value `source` maps to
 * provenance, not to a font-file format: an `AssetSource::System` family is a
 * platform/library face, everything else (a webfont captured from the client's
 * own site, an upload) is the brand's own — the screen's "Custom".
 */
function toTypefaces(fonts: FontAssets | undefined): BrandTypeface[] {
  if (!fonts) return [];
  return Object.keys(fonts)
    .sort()
    .flatMap((id) => {
      const font = fonts[id];
      if (!font) return [];
      return [
        {
          family: font.family,
          id,
          source:
            font.source && font.source.kind !== "system"
              ? ("custom" as const)
              : ("library" as const),
        },
      ];
    });
}

type TypographyTokens = Readonly<Record<string, BrandTypographyToken | null>>;

/**
 * `tokens.typography` → the text-style table, largest first (the type scale's
 * own reading order; the wire's key order is not meaningful).
 *
 * The kit stores `line_height` as a UNITLESS multiplier — the engine computes
 * `font_size * line_height` (`text_measure.rs:563`) — while the table's column
 * is px, so the mapper does that exact multiplication. A token that carries no
 * line height reports its font size (ratio 1); nothing is invented.
 */
function toTextStyles(
  typography: TypographyTokens | undefined,
): BrandTextStyle[] {
  if (!typography) return [];
  const styles = Object.keys(typography).flatMap((path) => {
    const style = resolveTypography(typography, path, 0);
    if (!style) return [];
    return [
      {
        fontFamily: style.font_family,
        fontSize: style.font_size,
        fontWeight: style.font_weight,
        id: path,
        lineHeight: Math.round(style.font_size * (style.line_height ?? 1)),
        name: humanize(stripPrefix(path, "type.")),
        // Usage guidance is not part of the kit's type tokens; the token's own
        // description is the only honest source and ingestion leaves it null.
        recommendedUse: typography[path]?.description ?? "",
      },
    ];
  });
  styles.sort(
    (left, right) =>
      right.fontSize - left.fontSize || left.id.localeCompare(right.id),
  );
  return styles;
}

function resolveTypography(
  typography: TypographyTokens,
  path: string,
  depth: number,
): Extract<
  BrandTypographyToken["value"]["default"],
  { kind: "style" }
> | null {
  if (depth > MAX_ALIAS_DEPTH) return null;
  const token = typography[path];
  if (!token) return null;
  const value = token.value.default;
  if (value.kind === "style") return value;
  return resolveTypography(typography, value.token, depth + 1);
}

function paletteFamily(path: string): string | null {
  if (!path.startsWith("palette.")) return null;
  return path.split(".")[1] ?? null;
}

/** Ramp stops sort numerically (`50` before `100`); everything else lexically. */
function compareColorPaths(left: string, right: string): number {
  const leftStop = Number(lastSegment(left));
  const rightStop = Number(lastSegment(right));
  const sameRamp =
    left.slice(0, left.lastIndexOf(".")) === right.slice(0, right.lastIndexOf("."));
  if (sameRamp && Number.isFinite(leftStop) && Number.isFinite(rightStop)) {
    return leftStop - rightStop;
  }
  return left.localeCompare(right);
}

function lastSegment(path: string): string | undefined {
  return path.split(".").at(-1);
}

function titleCase(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function stripPrefix(value: string, prefix: string): string {
  return value.startsWith(prefix) ? value.slice(prefix.length) : value;
}

/** `body.small` → `Body small`: a readable label, still the token's own words. */
function humanize(value: string): string {
  return titleCase(value.replaceAll(".", " ").replaceAll("_", " "));
}
