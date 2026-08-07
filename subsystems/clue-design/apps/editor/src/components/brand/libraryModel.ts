import type { AssetRecord } from "@/engine/contracts";
import type { AssetDescription } from "@/engine/brandLibrary";

/**
 * Pure view-model helpers for the brand asset library. Kept out of the React
 * component so the tag facets, search filter, and per-asset display fields are
 * testable in isolation and the page stays thin.
 */

export interface LibraryItem {
  record: AssetRecord;
  description: AssetDescription | undefined;
  /** Preferred display title: human description title, else label, else filename. */
  title: string;
  kind: string;
  tags: string[];
  createdAt: string | null;
  byteLength: number | null;
}

export interface TagFacet {
  tag: string;
  count: number;
}

function recordFilename(record: AssetRecord): string | null {
  return record.media?.filename ?? null;
}

export function assetCreatedAt(record: AssetRecord): string | null {
  const provenance = record.provenance as { created_at?: string } | undefined;
  return provenance?.created_at ?? null;
}

/** Ingested filenames carry content-hash prefixes ("6799cf04_Aeonik….otf") and
 * scrape labels are often the generic "image" — neither is a display name. */
function cleanDisplayName(value: string | null | undefined): string | null {
  const trimmed = value?.trim();
  if (!trimmed || trimmed === "image" || trimmed === "asset") return null;
  return trimmed.replace(/^[0-9a-f]{8,}[_-]/i, "");
}

/** Engine kinds are enum-speak ("raster_image"); the library talks human. */
export function humanKind(kind: string | null | undefined): string {
  switch (kind) {
    case "raster_image":
      return "image";
    case "vector":
      return "vector";
    case "font":
      return "font";
    case "document":
      return "document";
    default:
      return kind || "other";
  }
}

export function buildLibraryItem(
  record: AssetRecord,
  description: AssetDescription | undefined
): LibraryItem {
  const title =
    cleanDisplayName(description?.title) ||
    cleanDisplayName(record.label) ||
    cleanDisplayName(recordFilename(record)) ||
    record.id;
  const tags = Array.from(
    new Set([...(record.tags ?? []), ...(description?.tags ?? [])])
  ).filter((tag) => tag.length > 0);
  return {
    record,
    description,
    title,
    kind: humanKind(record.kind),
    tags,
    createdAt: assetCreatedAt(record),
    byteLength: record.media?.byte_length ?? null
  };
}

export function buildLibraryItems(
  records: AssetRecord[],
  descriptions: Record<string, AssetDescription>
): LibraryItem[] {
  return records
    .map((record) => buildLibraryItem(record, descriptions[record.id]))
    .sort((a, b) => (b.createdAt ?? "").localeCompare(a.createdAt ?? ""));
}

/** Tag facets across every item, sorted by descending count then name. */
export function computeTagFacets(items: LibraryItem[]): TagFacet[] {
  const counts = new Map<string, number>();
  for (const item of items) {
    for (const tag of item.tags) {
      counts.set(tag, (counts.get(tag) ?? 0) + 1);
    }
  }
  return Array.from(counts.entries())
    .map(([tag, count]) => ({ tag, count }))
    .sort((a, b) => b.count - a.count || a.tag.localeCompare(b.tag));
}

export function filterLibraryItems(
  items: LibraryItem[],
  activeTag: string | null,
  query: string
): LibraryItem[] {
  const needle = query.trim().toLowerCase();
  return items.filter((item) => {
    if (activeTag && !item.tags.includes(activeTag)) {
      return false;
    }
    if (needle) {
      const haystack = [
        item.title,
        item.record.label,
        item.description?.description ?? "",
        recordFilename(item.record) ?? ""
      ]
        .join(" ")
        .toLowerCase();
      if (!haystack.includes(needle)) {
        return false;
      }
    }
    return true;
  });
}

export function assetDimensions(record: AssetRecord): string | null {
  const raster = record.raster;
  if (raster?.pixel_width && raster.pixel_height) {
    return `${raster.pixel_width} × ${raster.pixel_height}`;
  }
  const vector = record.vector;
  if (vector?.width && vector.height) {
    return `${vector.width} × ${vector.height}`;
  }
  return null;
}

export function formatBytes(byteLength: number | null): string | null {
  if (byteLength === null || byteLength === undefined) {
    return null;
  }
  if (byteLength < 1024) {
    return `${byteLength} B`;
  }
  if (byteLength < 1024 * 1024) {
    return `${(byteLength / 1024).toFixed(1)} KB`;
  }
  return `${(byteLength / (1024 * 1024)).toFixed(1)} MB`;
}
