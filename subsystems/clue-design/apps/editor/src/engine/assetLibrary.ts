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

export interface GenerateAssetRequest {
  prompt: string;
  provider?: string;
  outputKind?: string;
  width?: number;
  height?: number;
  mimeType?: string;
  transparentBackground?: boolean;
  brandNotes?: string[];
  label?: string;
}

export interface AssetGenerateResult {
  asset: AssetRecord;
  deduplicated: boolean;
  diagnostics: Diagnostic[];
}

/** Default provider id for the text-to-image path (the Python image-gen seam). */
export const IMAGE_GEN_PROVIDER = "image-gen-v1";

/**
 * Generate a raster image through `POST /assets/generate`. The bytes are persisted
 * by the API exactly like an upload and a ready `AssetRecord` is returned; the editor
 * then places it with `buildNodePlacementOperations`. On a provider/config failure the
 * API returns a typed error (e.g. a 503 when the model is not configured) whose
 * `detail.message` / `LUMA*` code is surfaced to the user.
 */
export async function generateAsset(
  apiBaseUrl: string,
  request: GenerateAssetRequest
): Promise<AssetGenerateResult> {
  const response = await fetch(new URL("/assets/generate", apiBaseUrl), {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({
      provider: request.provider ?? IMAGE_GEN_PROVIDER,
      prompt: request.prompt,
      output_kind: request.outputKind ?? "raster_image",
      width: request.width,
      height: request.height,
      mime_type: request.mimeType,
      transparent_background: request.transparentBackground,
      brand_notes: request.brandNotes ?? [],
      label: request.label
    })
  });
  const payload = (await response.json().catch(() => ({}))) as {
    asset?: AssetRecord;
    deduplicated?: boolean;
    diagnostics?: Diagnostic[];
    detail?: { message?: string; code?: string };
  };
  if (!response.ok || !payload.asset) {
    const detail = payload.detail;
    throw new Error(
      detail?.message ?? detail?.code ?? `Image generation failed with status ${response.status}`
    );
  }
  return {
    asset: payload.asset,
    deduplicated: payload.deduplicated ?? false,
    diagnostics: payload.diagnostics ?? []
  };
}

export interface EditAssetRequest {
  /** The existing asset whose pixels are edited; the result is a new asset. */
  sourceAssetId: string;
  /** The edit instruction (or the fixed remove-background instruction). */
  prompt: string;
  provider?: string;
  outputKind?: string;
  transparentBackground?: boolean;
  brandNotes?: string[];
  label?: string;
}

/**
 * Edit an existing raster asset through `POST /assets/generate` with a
 * `source_asset_id` (Phase 3b). The API loads the source pixels, runs the
 * model edit, and returns a NEW ready `AssetRecord` whose `source` chains to
 * the parent (kind "edited"). Remove-background is this same call with the
 * fixed instruction + `transparentBackground: true`. Errors surface the same
 * typed `detail.message` / `LUMA*` code as generation.
 */
export async function editAsset(
  apiBaseUrl: string,
  request: EditAssetRequest
): Promise<AssetGenerateResult> {
  const response = await fetch(new URL("/assets/generate", apiBaseUrl), {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({
      provider: request.provider ?? IMAGE_GEN_PROVIDER,
      prompt: request.prompt,
      output_kind: request.outputKind ?? "raster_image",
      source_asset_id: request.sourceAssetId,
      transparent_background: request.transparentBackground,
      brand_notes: request.brandNotes ?? [],
      label: request.label
    })
  });
  const payload = (await response.json().catch(() => ({}))) as {
    asset?: AssetRecord;
    deduplicated?: boolean;
    diagnostics?: Diagnostic[];
    detail?: { message?: string; code?: string };
  };
  if (!response.ok || !payload.asset) {
    const detail = payload.detail;
    throw new Error(
      detail?.message ?? detail?.code ?? `Image edit failed with status ${response.status}`
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
