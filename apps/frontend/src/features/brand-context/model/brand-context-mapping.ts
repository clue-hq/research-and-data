import type { z } from "zod";
import type {
  BrandAsset,
  BrandAssetCategory,
  BrandColorGroupSchema,
  BrandColorSwatchSchema,
  BrandContextWorkspace,
  BrandTextStyle,
  BrandTypeface,
} from "./brand-context";
import {
  DesignAssetRecordSchema,
  type BrandColorToken,
  type BrandFontAsset,
  type BrandImageAsset,
  type BrandKitDetail,
  type BrandLogoAsset,
  type BrandTypographyToken,
  type DesignAssetRecord,
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
 * The authenticated BFF mount for the design API — the ONLY origin a browser
 * may load design bytes from (mirrors `design-editor/data/design-bff.ts`'s
 * `DESIGN_API_BFF_PREFIX`; duplicated as a literal so the pure model never
 * imports a data module).
 */
export const DESIGN_ASSET_BFF_PREFIX = "/api/clue/design/assets";

/** What a display field says when the store genuinely does not know. */
const UNKNOWN = "—";

export interface BrandContextMappingOptions {
  /**
   * `GET /assets/{id}` records for the kit's assets, keyed by asset id. The
   * kit carries only ids; filename, media type, byte length and geometry live
   * in the registry. A missing record degrades that one asset, never the page.
   */
  readonly assetRecords?: ReadonlyMap<string, DesignAssetRecord>;
}

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
  options: BrandContextMappingOptions = {},
): BrandContextWorkspace {
  const json = kit.brand_kit_json;
  return {
    assets: toAssets(kit, options.assetRecords),
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

  for (const path of Object.keys(colors).sort(comparePaths)) {
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

/** One asset as the KIT describes it, before the registry fills in the facts. */
interface KitAssetEntry {
  readonly assetId: string;
  readonly category: BrandAssetCategory;
  readonly description: string;
  /** From a logo variant, when the kit measured one. */
  readonly dimensions: string | null;
  readonly fallbackName: string;
  readonly mimeType: string | null;
}

/**
 * The kit's logos then its images, deduped by asset id.
 *
 * Category is the one lossy step in this mapping: the screen's filter is a
 * closed four-value enum (`logo | background | mockup | ai-generated`) while
 * the kit's image `role` vocabulary is `photo | illustration | screenshot |
 * icon | og_image`. Logos are logos, a captured `screenshot` is the screen's
 * "mockup", and every other role falls to `background`. `ai-generated` is
 * unreachable from website ingestion — nothing here generates imagery.
 */
function kitAssetEntries(kit: BrandKitDetail): KitAssetEntry[] {
  const logos: Readonly<Record<string, BrandLogoAsset | null>> =
    kit.brand_kit_json.assets?.logos ?? {};
  const images: Readonly<Record<string, BrandImageAsset | null>> =
    kit.brand_kit_json.assets?.images ?? {};
  const entries: KitAssetEntry[] = [];
  const seen = new Set<string>();

  for (const key of Object.keys(logos).sort(comparePaths)) {
    const logo = logos[key];
    const variants = logo?.variants ?? [];
    for (const variant of variants) {
      if (!logo || seen.has(variant.asset_id)) continue;
      seen.add(variant.asset_id);
      entries.push({
        assetId: variant.asset_id,
        category: "logo",
        description: logo.description ?? logo.usage_note ?? "",
        dimensions: dimensionLabel(variant.width, variant.height),
        fallbackName:
          variants.length > 1 && variant.name
            ? `${key} ${variant.name}`
            : key,
        mimeType: null,
      });
    }
  }

  for (const key of Object.keys(images).sort(comparePaths)) {
    const image = images[key];
    if (!image || seen.has(image.asset_id)) continue;
    seen.add(image.asset_id);
    entries.push({
      assetId: image.asset_id,
      category: image.role === "screenshot" ? "mockup" : "background",
      description: image.description ?? image.usage_note ?? "",
      dimensions: null,
      fallbackName: image.title ?? key,
      mimeType: image.mime_type ?? null,
    });
  }

  return entries;
}

/** Every asset id the kit references — the registry reads the repository makes. */
export function brandKitAssetIds(kit: BrandKitDetail): string[] {
  return kitAssetEntries(kit).map((entry) => entry.assetId);
}

/** `GET /assets/{id}` bodies keyed by asset id; unreadable ones are dropped. */
export function parseAssetRecords(
  raw: Readonly<Record<string, unknown>> | undefined,
): Map<string, DesignAssetRecord> {
  const records = new Map<string, DesignAssetRecord>();
  for (const [id, body] of Object.entries(raw ?? {})) {
    const parsed = DesignAssetRecordSchema.safeParse(body);
    if (parsed.success) records.set(id, parsed.data);
  }
  return records;
}

/**
 * The assets panel's rows. Bytes are always addressed through the BFF — a
 * browser must never reach the design API directly. No kit models a gradient
 * (`constraints.allow_gradients` is a policy flag, not a colour stop list), so
 * every asset here is an image; a gradient tile would be invented.
 */
function toAssets(
  kit: BrandKitDetail,
  records: ReadonlyMap<string, DesignAssetRecord> | undefined,
): BrandAsset[] {
  return kitAssetEntries(kit).map((entry) => {
    const stored = records?.get(entry.assetId);
    const record = stored?.asset;
    const media = record?.media;
    const geometry = record?.vector ?? record?.raster;
    const createdAt = stored?.created_at ?? kit.brand_kit.created_at ?? "";
    return {
      category: entry.category,
      createdAt,
      createdLabel: dateLabel(createdAt),
      description: entry.description,
      dimensions:
        entry.dimensions ??
        dimensionLabel(geometry?.width, geometry?.height) ??
        UNKNOWN,
      id: entry.assetId,
      name: record?.label ?? media?.filename ?? entry.fallbackName,
      sizeBytes: media?.byte_length ?? 0,
      sizeLabel:
        media?.byte_length != null ? byteLabel(media.byte_length) : UNKNOWN,
      type: mediaTypeLabel(media?.mime_type ?? entry.mimeType),
      visual: {
        imagePath: `${DESIGN_ASSET_BFF_PREFIX}/${encodeURIComponent(entry.assetId)}/bytes`,
        kind: "image" as const,
      },
    };
  });
}

function dimensionLabel(
  width: number | null | undefined,
  height: number | null | undefined,
): string | null {
  if (width == null || height == null) return null;
  return `${trimNumber(width)}×${trimNumber(height)}px`;
}

function trimNumber(value: number): string {
  return String(Number(value.toFixed(2)));
}

function byteLabel(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

const DATE_LABEL = new Intl.DateTimeFormat("en-US", {
  day: "numeric",
  month: "short",
  timeZone: "UTC",
  year: "numeric",
});

function dateLabel(iso: string): string {
  const at = Date.parse(iso);
  return Number.isNaN(at) ? UNKNOWN : DATE_LABEL.format(at);
}

/** `image/svg+xml` → `SVG`. The store's own media type, never a guess. */
function mediaTypeLabel(mime: string | null | undefined): string {
  const subtype = mime?.split("/")[1]?.split("+")[0];
  return subtype ? subtype.toUpperCase() : UNKNOWN;
}

function paletteFamily(path: string): string | null {
  if (!path.startsWith("palette.")) return null;
  return path.split(".")[1] ?? null;
}

/** Sibling numeric segments sort numerically (`50` before `100`, `img.2`
 * before `img.10`); everything else lexically. */
function comparePaths(left: string, right: string): number {
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
