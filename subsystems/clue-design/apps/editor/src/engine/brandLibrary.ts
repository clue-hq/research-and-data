import type { AssetRecord } from "./contracts";
import { fetchAssets } from "./assetLibrary";
import { lumenFetch } from "./editorConfig";

/**
 * Brand-section library + ingest client (slice 4).
 *
 * Follows documentStore.ts conventions: every call takes an explicit
 * `{ apiBaseUrl }` options bag and throws on a non-2xx response. Asset listing
 * reuses the workspace `GET /assets` shapes via `assetLibrary.fetchAssets`;
 * descriptions are the slice-3 DescriptionStore rows; ingest posts are the
 * three multipart/website intake routes plus job polling.
 */

export interface BrandLibraryOptions {
  apiBaseUrl: string;
}

const ASSET_LIBRARY_LIMIT = 200;
const DESCRIPTION_ID_CAP = 200;

export async function fetchLibraryAssets(
  options: BrandLibraryOptions
): Promise<AssetRecord[]> {
  return fetchAssets(options.apiBaseUrl, { limit: ASSET_LIBRARY_LIMIT });
}

// -- asset descriptions (slice-3 DescriptionStore) -------------------------

export type DescriptionOrigin = "engine" | "human";

export interface AssetDescription {
  title?: string | null;
  description?: string | null;
  usage?: string | null;
  tags?: string[];
  origin?: DescriptionOrigin | string;
  updated_at?: string | null;
}

export interface DescriptionPatch {
  title?: string;
  description?: string;
  usage?: string;
  tags?: string[];
}

export async function fetchDescriptions(
  options: BrandLibraryOptions,
  assetIds: string[]
): Promise<Record<string, AssetDescription>> {
  const ids = assetIds.slice(0, DESCRIPTION_ID_CAP);
  if (ids.length === 0) {
    return {};
  }
  const url = new URL("/assets/descriptions", options.apiBaseUrl);
  url.searchParams.set("asset_ids", ids.join(","));
  const response = await lumenFetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`Asset descriptions failed with status ${response.status}`);
  }
  const payload = (await response.json()) as {
    descriptions?: Record<string, AssetDescription>;
  };
  return payload.descriptions ?? {};
}

export async function saveDescription(
  options: BrandLibraryOptions,
  assetId: string,
  patch: DescriptionPatch
): Promise<AssetDescription> {
  const response = await lumenFetch(
    new URL(`/assets/${assetId}/description`, options.apiBaseUrl),
    {
      method: "PUT",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(patch)
    }
  );
  const payload = (await response.json().catch(() => ({}))) as
    | AssetDescription
    | { detail?: { message?: string; code?: string } };
  if (!response.ok) {
    const detail = (payload as { detail?: { message?: string; code?: string } }).detail;
    throw new Error(
      detail?.message ?? detail?.code ?? `Saving description failed with status ${response.status}`
    );
  }
  return payload as AssetDescription;
}

// -- ingestion jobs --------------------------------------------------------

export type IngestJobKind = "website" | "pdf" | "asset_upload";
/** `succeeded_with_gaps` (spec 2026-10-25): a kit was published, with failed descriptions, ad
 * analyses or card listed as the job's gaps — finished, and read like `succeeded`. */
export type IngestJobStatus = "queued" | "running" | "succeeded" | "succeeded_with_gaps" | "failed";

export interface IngestJob {
  job_id: string;
  kind: IngestJobKind | string;
  status: IngestJobStatus | string;
  stage: string | null;
  progress: number | null;
  brand_kit_id: string | null;
  brand_kit_version: number | null;
  error: unknown;
  created_at: string;
  updated_at: string;
}

export function isTerminalJob(job: IngestJob): boolean {
  return isSucceededJob(job) || job.status === "failed";
}

/** Finished with a kit — cleanly or with gaps a workspace repair can heal. */
export function isSucceededJob(job: IngestJob): boolean {
  return job.status === "succeeded" || job.status === "succeeded_with_gaps";
}

function readJobResponse(payload: { job?: IngestJob }): IngestJob {
  if (!payload.job) {
    throw new Error("Ingestion response did not include a job");
  }
  return payload.job;
}

async function postIngest(
  options: BrandLibraryOptions,
  path: string,
  body: BodyInit,
  headers?: HeadersInit
): Promise<IngestJob> {
  const response = await lumenFetch(new URL(path, options.apiBaseUrl), {
    method: "POST",
    headers,
    body
  });
  const payload = (await response.json().catch(() => ({}))) as {
    job?: IngestJob;
    detail?: { message?: string; code?: string } | string;
  };
  if (!response.ok) {
    const detail = payload.detail;
    const message =
      typeof detail === "string" ? detail : detail?.message ?? detail?.code;
    throw new Error(message ?? `Ingest failed with status ${response.status}`);
  }
  return readJobResponse(payload);
}

export async function startWebsiteIngest(
  options: BrandLibraryOptions,
  url: string,
  name?: string
): Promise<IngestJob> {
  return postIngest(
    options,
    "/brand-kits/ingest/website",
    JSON.stringify({ url, name: name?.trim() ? name.trim() : undefined }),
    { "Content-Type": "application/json", Accept: "application/json" }
  );
}

export async function startPdfIngest(
  options: BrandLibraryOptions,
  file: File,
  name?: string
): Promise<IngestJob> {
  const form = new FormData();
  form.append("file", file);
  if (name?.trim()) {
    form.append("name", name.trim());
  }
  return postIngest(options, "/brand-kits/ingest/pdf", form);
}

export async function startAssetIngest(
  options: BrandLibraryOptions,
  files: File[],
  name?: string
): Promise<IngestJob> {
  const form = new FormData();
  for (const file of files) {
    form.append("files", file);
  }
  if (name?.trim()) {
    form.append("name", name.trim());
  }
  return postIngest(options, "/brand-kits/ingest/assets", form);
}

export async function fetchIngestJob(
  options: BrandLibraryOptions,
  jobId: string
): Promise<IngestJob> {
  const response = await lumenFetch(
    new URL(`/brand-kits/ingest/${jobId}`, options.apiBaseUrl),
    { headers: { Accept: "application/json" } }
  );
  const payload = (await response.json().catch(() => ({}))) as { job?: IngestJob };
  if (!response.ok) {
    throw new Error(`Ingestion job failed with status ${response.status}`);
  }
  return readJobResponse(payload);
}

export async function fetchIngestJobs(
  options: BrandLibraryOptions
): Promise<IngestJob[]> {
  const response = await lumenFetch(new URL("/brand-kits/ingest", options.apiBaseUrl), {
    headers: { Accept: "application/json" }
  });
  if (!response.ok) {
    throw new Error(`Ingestion job list failed with status ${response.status}`);
  }
  const payload = (await response.json()) as { jobs?: IngestJob[] };
  return payload.jobs ?? [];
}
