import type { AssetRecord } from "../engine/scene/contracts";

/**
 * The asset library, composed on the client (spec approach 1): the workspace registry with the
 * brand kit's own pictures pinned first. Pure — the Brand context page imports the same functions
 * so the two surfaces can never disagree on what the library is.
 */

export type AssetLibraryCategory = "logo" | "background" | "mockup" | "ai-generated" | "upload";

export interface KitLibraryEntry {
  assetId: string;
  category: "logo" | "background" | "mockup";
}

export interface AssetLibraryItem {
  record: AssetRecord;
  /** A brand-kit item — listed first and badged "Brand". */
  pinned: boolean;
  /** The asset currently placed on the selected node. */
  inUse: boolean;
  category: AssetLibraryCategory;
}

/** Kit logo variants then kit images, kit order, deduped — from a `brand_kit_json` of unknown
 * shape (the editor's kit payload is typed loosely; narrow, never trust). */
export function kitLibraryEntries(kit: unknown): KitLibraryEntry[] {
  const assets = (kit as { assets?: unknown } | null | undefined)?.assets;
  if (!assets || typeof assets !== "object") return [];
  const { logos, images } = assets as { logos?: unknown; images?: unknown };
  const entries: KitLibraryEntry[] = [];
  const seen = new Set<string>();
  const push = (assetId: unknown, category: KitLibraryEntry["category"]) => {
    if (typeof assetId !== "string" || assetId.length === 0 || seen.has(assetId)) return;
    seen.add(assetId);
    entries.push({ assetId, category });
  };
  if (logos && typeof logos === "object") {
    for (const logo of Object.values(logos as Record<string, unknown>)) {
      const variants = (logo as { variants?: unknown } | null)?.variants;
      if (!Array.isArray(variants)) continue;
      for (const variant of variants) push((variant as { asset_id?: unknown })?.asset_id, "logo");
    }
  }
  if (images && typeof images === "object") {
    for (const image of Object.values(images as Record<string, unknown>)) {
      if (!image || typeof image !== "object") continue;
      const { asset_id, role } = image as { asset_id?: unknown; role?: unknown };
      push(asset_id, role === "screenshot" ? "mockup" : "background");
    }
  }
  return entries;
}

/** Structural on purpose: the Brand context page passes its own zod-parsed list record. */
export function registryCategory(record: { source: { kind: string } }): "ai-generated" | "upload" {
  return record.source.kind === "generated" ? "ai-generated" : "upload";
}

export function composeAssetLibrary({ registry, kitEntries, inUseAssetId }: {
  registry: readonly AssetRecord[];
  kitEntries: readonly KitLibraryEntry[];
  inUseAssetId: string | null;
}): AssetLibraryItem[] {
  const byId = new Map<string, AssetRecord>();
  for (const record of registry) {
    if (record.status === "archived" || byId.has(record.id)) continue;
    byId.set(record.id, record);
  }
  const items: AssetLibraryItem[] = [];
  const placed = new Set<string>();
  for (const entry of kitEntries) {
    const record = byId.get(entry.assetId);
    if (!record || placed.has(entry.assetId)) continue;
    placed.add(entry.assetId);
    items.push({ record, pinned: true, inUse: record.id === inUseAssetId, category: entry.category });
  }
  for (const record of byId.values()) {
    if (placed.has(record.id)) continue;
    items.push({ record, pinned: false, inUse: record.id === inUseAssetId, category: registryCategory(record) });
  }
  return items;
}

export function filterAssetLibrary(
  items: readonly AssetLibraryItem[],
  filter: { query: string; category: AssetLibraryCategory | "all" },
): AssetLibraryItem[] {
  const query = filter.query.trim().toLocaleLowerCase();
  return items.filter((item) => {
    if (filter.category !== "all" && item.category !== filter.category) return false;
    if (!query) return true;
    const haystack = `${item.record.label} ${item.record.media?.filename ?? ""}`.toLocaleLowerCase();
    return haystack.includes(query);
  });
}
