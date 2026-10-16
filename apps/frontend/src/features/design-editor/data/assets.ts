import type { AssetRecord } from "../engine/asset-types";
import { DESIGN_API_BFF_PREFIX } from "./design-bff";

/**
 * W4.2 (mapping contract §1 row 12, lane B): the asset-store upload behind the
 * inspector's Replace-image control.
 *
 * The design API's `POST /assets` speaks workspace-header auth and never faces
 * a browser directly, so this client posts to the BFF mount instead — the
 * proxy forwards the content-type + raw body and stamps the workspace header
 * server-side. The FormData body deliberately carries NO hand-set
 * `Content-Type`: the browser writes the multipart boundary, and setting the
 * header ourselves would strip it and make the body unparseable upstream.
 *
 * Placement stays canonical: this client only mints the record; the document
 * change is the caller's `upsert_asset` + `replace_asset` batch (see
 * `hooks/use-replace-image.ts`), exactly like the upstream editor.
 */

/** A typed refusal from the asset upload seam (design `detail` code + status). */
export class WebAssetUploadError extends Error {
  readonly code: string | null;
  readonly status: number;

  constructor(message: string, options: { code?: string | null; status: number }) {
    super(message);
    this.name = "WebAssetUploadError";
    this.code = options.code ?? null;
    this.status = options.status;
  }
}

interface AssetUploadPayload {
  asset?: AssetRecord;
  deduplicated?: boolean;
  /** FastAPI's refusal body: an object for the ingest errors, a bare string
   * for the plain `HTTPException(detail="…")` cases (413 size, 400 license). */
  detail?: { code?: string; message?: string } | string;
}

export async function uploadWebAsset(
  file: File,
  { fetchImpl }: { fetchImpl?: typeof fetch } = {},
): Promise<AssetRecord> {
  const doFetch: typeof fetch = fetchImpl ?? ((input, init) => fetch(input, init));
  const form = new FormData();
  form.append("file", file);
  form.append("label", file.name);
  const response = await doFetch(`${DESIGN_API_BFF_PREFIX}/assets`, {
    method: "POST",
    body: form,
  });

  let payload: AssetUploadPayload = {};
  try {
    payload = (await response.json()) as AssetUploadPayload;
  } catch {
    // A non-JSON refusal (or an empty body) keeps the status-shaped message.
  }

  if (!response.ok || !payload.asset) {
    const detail = payload.detail;
    const message =
      typeof detail === "string"
        ? detail
        : (detail?.message ??
          detail?.code ??
          `Image upload failed with status ${response.status}`);
    throw new WebAssetUploadError(message, {
      code: typeof detail === "string" ? null : (detail?.code ?? null),
      status: response.status,
    });
  }
  return payload.asset;
}

/** The registry kinds that paint as pictures — what the asset-library picker and the Brand
 * context Assets page list. Fonts, documents and `other` never appear there. */
export const IMAGE_ASSET_KINDS = ["raster_image", "vector", "logo"] as const;

const LIST_PAGE_SIZE = 200;

/** A typed refusal from the registry list seam — the same shape as the upload's. */
export class WebAssetListError extends Error {
  readonly code: string | null;
  readonly status: number;
  constructor(message: string, options: { code?: string | null; status: number }) {
    super(message);
    this.name = "WebAssetListError";
    this.code = options.code ?? null;
    this.status = options.status;
  }
}

interface AssetListPayload {
  assets?: AssetRecord[];
  detail?: { code?: string; message?: string } | string;
}

/**
 * Every non-archived image asset in the workspace registry, through the authenticated BFF
 * (`GET /assets`), one request per image kind (the route filters a single `kind`), paged while a
 * page comes back full. Order is kind order, then the server's own (`updated_at desc`).
 */
export async function listImageAssets(
  { fetchImpl }: { fetchImpl?: typeof fetch } = {},
): Promise<AssetRecord[]> {
  const doFetch: typeof fetch = fetchImpl ?? ((input, init) => fetch(input, init));
  const records: AssetRecord[] = [];
  for (const kind of IMAGE_ASSET_KINDS) {
    for (let offset = 0; ; offset += LIST_PAGE_SIZE) {
      const response = await doFetch(
        `${DESIGN_API_BFF_PREFIX}/assets?kind=${kind}&include_archived=false&limit=${LIST_PAGE_SIZE}&offset=${offset}`,
      );
      let payload: AssetListPayload = {};
      try {
        payload = (await response.json()) as AssetListPayload;
      } catch {
        // A non-JSON body keeps the status-shaped message below.
      }
      if (!response.ok || !Array.isArray(payload.assets)) {
        const detail = payload.detail;
        const message =
          typeof detail === "string"
            ? detail
            : (detail?.message ?? detail?.code ?? `Asset list failed with status ${response.status}`);
        throw new WebAssetListError(message, {
          code: typeof detail === "string" ? null : (detail?.code ?? null),
          status: response.status,
        });
      }
      records.push(...payload.assets);
      if (payload.assets.length < LIST_PAGE_SIZE) break;
    }
  }
  return records;
}

/** One logo version a logo search found: what it is, which background it is for (null when the
 * source made no such claim), who served it, and an inline preview. Not yet in the registry. */
export interface LogoSearchResult {
  asset_id: string;
  kind: string;
  background: "light" | "dark" | null;
  source: string;
  content_type: string;
  preview: string;
}

export interface LogoSearchResponse {
  /** The company's domain as the lookup understood it; null when nothing was found. */
  name: string | null;
  logos: LogoSearchResult[];
}

/** A typed refusal from the logo search seam — the same shape as the upload's. */
export class LogoSearchError extends Error {
  readonly code: string | null;
  readonly status: number;
  constructor(message: string, options: { code?: string | null; status: number }) {
    super(message);
    this.name = "LogoSearchError";
    this.code = options.code ?? null;
    this.status = options.status;
  }
}

async function postLogoSearch<T>(
  path: string,
  body: Record<string, string>,
  fallback: string,
  fetchImpl?: typeof fetch,
): Promise<T> {
  const doFetch: typeof fetch = fetchImpl ?? ((input, init) => fetch(input, init));
  const response = await doFetch(`${DESIGN_API_BFF_PREFIX}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  let payload: (T & { detail?: { code?: string; message?: string } | string }) | null = null;
  try {
    payload = (await response.json()) as T & { detail?: { code?: string; message?: string } | string };
  } catch {
    // A non-JSON body keeps the fallback message below.
  }
  if (!response.ok || payload === null) {
    const detail = payload?.detail;
    const message = typeof detail === "string" ? detail : (detail?.message ?? fallback);
    throw new LogoSearchError(message, {
      code: typeof detail === "string" ? null : (detail?.code ?? null),
      status: response.status,
    });
  }
  return payload;
}

/** The asset library's Logo search (`POST /assets/logo-search`): every version found for any
 * company's website, as previews. Saves nothing. */
export async function searchLogos(
  url: string,
  { fetchImpl }: { fetchImpl?: typeof fetch } = {},
): Promise<LogoSearchResponse> {
  const payload = await postLogoSearch<Partial<LogoSearchResponse>>(
    "/assets/logo-search",
    { url },
    "Logo search failed. Try again.",
    fetchImpl,
  );
  return { name: payload.name ?? null, logos: Array.isArray(payload.logos) ? payload.logos : [] };
}

/** Save the ONE version the person clicked as a workspace asset (`POST /assets/logo-search/save`).
 * Placement stays the caller's. */
export async function saveSearchedLogo(
  url: string,
  assetId: string,
  { fetchImpl }: { fetchImpl?: typeof fetch } = {},
): Promise<AssetRecord> {
  const payload = await postLogoSearch<{ asset?: AssetRecord }>(
    "/assets/logo-search/save",
    { url, asset_id: assetId },
    "That logo couldn't be saved. Try again.",
    fetchImpl,
  );
  if (!payload.asset) {
    throw new LogoSearchError("That logo couldn't be saved. Try again.", { status: 200 });
  }
  return payload.asset;
}
