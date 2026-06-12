import type { AssetPlacement, AssetRecord, Diagnostic, NodeId, Operation, SlotId } from "./contracts";

/**
 * Workspace asset library client (Phase E slice E7).
 *
 * The browser talks to the persistence API for listing, uploading, and
 * thumbnails; placement onto the document stays purely canonical: the
 * panel emits `upsert_asset` + `place_asset_in_node`/`place_asset_in_slot`
 * operations through the editor's normal operation path, so library
 * usage is recorded exactly like any other edit.
 */

export interface AssetLibraryQuery {
  kind?: string;
  q?: string;
  includeArchived?: boolean;
  limit?: number;
  offset?: number;
}

export interface AssetUploadResult {
  asset: AssetRecord;
  deduplicated: boolean;
  diagnostics: Diagnostic[];
}

export async function fetchAssets(
  apiBaseUrl: string,
  query: AssetLibraryQuery = {}
): Promise<AssetRecord[]> {
  const url = new URL("/assets", apiBaseUrl);
  if (query.kind) {
    url.searchParams.set("kind", query.kind);
  }
  if (query.q) {
    url.searchParams.set("q", query.q);
  }
  if (query.includeArchived) {
    url.searchParams.set("include_archived", "true");
  }
  if (query.limit !== undefined) {
    url.searchParams.set("limit", String(query.limit));
  }
  if (query.offset !== undefined) {
    url.searchParams.set("offset", String(query.offset));
  }
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`Asset list failed with status ${response.status}`);
  }
  const payload = (await response.json()) as { assets?: AssetRecord[] };
  return payload.assets ?? [];
}

export async function uploadAsset(
  apiBaseUrl: string,
  file: File,
  fields: { label?: string; kind?: string; uploadedBy?: string; tags?: string } = {}
): Promise<AssetUploadResult> {
  const form = new FormData();
  form.append("file", file);
  if (fields.label) {
    form.append("label", fields.label);
  }
  if (fields.kind) {
    form.append("kind", fields.kind);
  }
  if (fields.uploadedBy) {
    form.append("uploaded_by", fields.uploadedBy);
  }
  if (fields.tags) {
    form.append("tags", fields.tags);
  }
  const response = await fetch(new URL("/assets", apiBaseUrl), {
    method: "POST",
    body: form
  });
  const payload = (await response.json()) as {
    asset?: AssetRecord;
    deduplicated?: boolean;
    diagnostics?: Diagnostic[];
    detail?: { message?: string; code?: string };
  };
  if (!response.ok || !payload.asset) {
    const detail = payload.detail;
    throw new Error(
      detail?.message ?? detail?.code ?? `Asset upload failed with status ${response.status}`
    );
  }
  return {
    asset: payload.asset,
    deduplicated: payload.deduplicated ?? false,
    diagnostics: payload.diagnostics ?? []
  };
}

export function assetThumbnailUrl(apiBaseUrl: string, assetId: string): string {
  return new URL(`/assets/${assetId}/thumbnail`, apiBaseUrl).toString();
}

export function assetBytesUrl(apiBaseUrl: string, assetId: string): string {
  return new URL(`/assets/${assetId}/bytes`, apiBaseUrl).toString();
}

/**
 * Canonical placement: register the library record on the document, then
 * place it into the target node. Replacing an image re-runs the same pair
 * against the same node id, preserving node identity and slot bindings.
 */
export function buildNodePlacementOperations(
  record: AssetRecord,
  nodeId: NodeId,
  placement: AssetPlacement = {}
): Operation[] {
  return [
    { kind: "upsert_asset", asset: record },
    {
      kind: "place_asset_in_node",
      node_id: nodeId,
      asset_id: record.id,
      placement: withDefaultAlt(record, placement)
    }
  ];
}

export function buildSlotPlacementOperations(
  record: AssetRecord,
  slotId: SlotId,
  placement: AssetPlacement = {}
): Operation[] {
  return [
    { kind: "upsert_asset", asset: record },
    {
      kind: "place_asset_in_slot",
      slot_id: slotId,
      asset_id: record.id,
      placement: withDefaultAlt(record, placement)
    }
  ];
}

function withDefaultAlt(record: AssetRecord, placement: AssetPlacement): AssetPlacement {
  return {
    ...placement,
    alt_text: placement.alt_text ?? record.label
  };
}
