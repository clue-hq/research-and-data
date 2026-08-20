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
  // Workspace auth is the BFF's job — the browser never stamps headers.
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
  // Workspace auth is the BFF's job — the browser never stamps headers.
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
  // Workspace auth is the BFF's job — the browser never stamps headers.
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
  // Workspace auth is the BFF's job — the browser never stamps headers.
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

const SHA256_HEX = /^[0-9a-f]{64}$/;

function usableDigest(digest: { algorithm?: string; value?: string } | null | undefined): string | null {
  if (digest && digest.algorithm === "sha256" && digest.value && SHA256_HEX.test(digest.value)) {
    return digest.value;
  }
  return null;
}

/**
 * Public content-addressed bytes URL for a record, or null when unfetchable.
 *
 * Browser contexts that render assets — `<img src>`, the canvas image
 * cache's bare fetcher — cannot send the workspace header, and the registry
 * endpoints (`/assets/{id}/bytes|thumbnail`) are workspace-gated, so the
 * ONLY servable URL shape for them is `/asset-store/{digest}` (O4-exempt,
 * gated by the unguessable sha256 itself — the same URLs lumen-web's
 * published pages emit). No digest ⇒ null; an empty image is honest, a
 * guaranteed-401 URL is not.
 */
export function publicAssetBytesUrl(
  apiBaseUrl: string,
  record: AssetRecord | null | undefined
): string | null {
  const digest = usableDigest(record?.media?.digest);
  return digest ? assetStoreBytesUrl(apiBaseUrl, digest) : null;
}

/** Thumbnail flavor of `publicAssetBytesUrl`: prefers the thumbnail's own
 * digest (the API stamps it at the DTO boundary), falls back to full bytes —
 * a heavier image is still a correct one — then null. */
export function publicAssetThumbnailUrl(
  apiBaseUrl: string,
  record: AssetRecord | null | undefined
): string | null {
  const thumbDigest = usableDigest(record?.media?.thumbnail?.digest);
  if (thumbDigest) {
    return assetStoreBytesUrl(apiBaseUrl, thumbDigest);
  }
  return publicAssetBytesUrl(apiBaseUrl, record);
}

export interface AssetRecordOptions {
  apiBaseUrl: string;
  fetchImpl?: typeof fetch;
}

/** One registry record (`GET /assets/{id}`), or null when unknown — the
 * resolver behind id-only `<img>` sites (kit JSON variants, stored logo
 * ids), which look up the record to learn its public digest. */
export async function fetchAssetRecord(
  // Workspace auth is the BFF's job — the browser never stamps headers.
  { apiBaseUrl, fetchImpl = fetch }: AssetRecordOptions,
  assetId: string
): Promise<AssetRecord | null> {
  const response = await fetchImpl(new URL(`/assets/${encodeURIComponent(assetId)}`, apiBaseUrl));
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`asset record fetch failed (HTTP ${response.status})`);
  }
  const payload = (await response.json()) as { asset?: AssetRecord };
  return payload.asset ?? null;
}

/** Content-addressed bytes URL (`/asset-store/{digest}`) — immutable,
 * cache-friendly, and independent of the asset REGISTRY. */
export function assetStoreBytesUrl(apiBaseUrl: string, digestValue: string): string {
  return new URL(`/asset-store/${digestValue}`, apiBaseUrl).toString();
}

/**
 * Resolve an asset's bytes URL from the SCENE's own record — the same source
 * of truth server exports resolve from. An asset any producer put into the
 * scene (the deepagent's generated imagery, edits, QR codes) is servable by
 * its content digest even when nothing registered it in the asset library.
 * Records without a usable sha256 digest — and asset ids the scene does not
 * carry at all (dangling references) — resolve to null (unfetchable, which
 * the canvas image cache models as a skipped load). The old registry
 * fallback (`/assets/{id}/bytes`) was a lie in this context: the cache
 * fetches bare (no workspace header), so that URL could only ever 401.
 */
export function sceneAssetBytesUrl(
  apiBaseUrl: string,
  assets: Record<string, AssetRecord> | undefined,
  assetId: string
): string | null {
  const digest = usableDigest(assets?.[assetId]?.media?.digest);
  return digest ? assetStoreBytesUrl(apiBaseUrl, digest) : null;
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
