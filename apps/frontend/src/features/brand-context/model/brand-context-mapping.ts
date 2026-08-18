import type {
  BrandColorGroup,
  BrandColorSwatch,
  BrandContextWorkspace,
} from "./brand-context";
import type { BrandColorToken, BrandKitDetail } from "./brand-kit";

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
    textStyles: [],
    typefaces: [],
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
