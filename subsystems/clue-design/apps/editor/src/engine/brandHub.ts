/**
 * Brand hub data layer — the fetch wrappers the /brand kit pages compose.
 *
 * Same contract shape as documentStore.ts: every call takes an explicit
 * `{ apiBaseUrl }` options object (read at call time from `editorApiBaseUrl()`),
 * wraps `fetch` so it is never stored bare, and throws on any non-2xx so the
 * page's error branch owns the message. The brand section is read-only in v1 —
 * the only mutation here is approval (setBrandKitApproval).
 */

export interface BrandHubOptions {
  apiBaseUrl: string;
  fetchImpl?: typeof fetch;
}

/** A latest-version kit summary, from `GET /brand-kits` / the detail dto's
 * `brand_kit` block. Fields beyond the spec's minimum are kept optional so the
 * detail summary (which carries modes/tokens/assets) parses through the same
 * type. */
export interface BrandKitListEntry {
  id: string;
  version: number;
  name: string;
  approval_status: string | null;
  product_ready: boolean;
  source: string | null;
  description: string | null;
  created_at: string | null;
  updated_at: string | null;
}

/** The flattened detail payload the review page renders: the summary, the raw
 * kit JSON (colors/typography/logos/…), the ingestion `brand_summary` (which
 * carries the `ingestion` report), and the diagnostics list. */
export interface BrandKitDetail {
  brandKit: BrandKitListEntry;
  kitJson: any;
  summary: any;
  diagnostics: any[];
}

function toListEntry(raw: any): BrandKitListEntry {
  const record = (raw ?? {}) as Record<string, unknown>;
  return {
    id: String(record.id ?? ""),
    version: typeof record.version === "number" ? record.version : 0,
    name: typeof record.name === "string" ? record.name : "Untitled kit",
    approval_status:
      typeof record.approval_status === "string" ? record.approval_status : null,
    product_ready: record.product_ready === true,
    source: typeof record.source === "string" ? record.source : null,
    description: typeof record.description === "string" ? record.description : null,
    created_at: typeof record.created_at === "string" ? record.created_at : null,
    updated_at: typeof record.updated_at === "string" ? record.updated_at : null
  };
}

/** Read the diagnostics list off a detail dto. The API returns
 * `{ audit, current, latest }`; `latest` is the deduped set the review page
 * wants. Tolerates a bare array too (older shape). */
function toDiagnostics(raw: unknown): any[] {
  if (Array.isArray(raw)) {
    return raw;
  }
  if (raw && typeof raw === "object") {
    const views = raw as Record<string, unknown>;
    if (Array.isArray(views.latest)) return views.latest;
    if (Array.isArray(views.audit)) return views.audit;
  }
  return [];
}

/** All stored kits (latest version each) for the /brand list. */
export async function fetchBrandKitList(
  { apiBaseUrl, fetchImpl = fetch }: BrandHubOptions
): Promise<BrandKitListEntry[]> {
  const response = await fetchImpl(new URL("/brand-kits", apiBaseUrl));
  if (!response.ok) {
    throw new Error(`brand kit list failed (HTTP ${response.status})`);
  }
  const payload = (await response.json()) as unknown;
  return Array.isArray(payload) ? payload.map(toListEntry) : [];
}

/** One kit's full review payload (`GET /brand-kits/{id}`). */
export async function fetchBrandKitDetailFull(
  { apiBaseUrl, fetchImpl = fetch }: BrandHubOptions,
  brandKitId: string
): Promise<BrandKitDetail> {
  const response = await fetchImpl(
    new URL(`/brand-kits/${encodeURIComponent(brandKitId)}`, apiBaseUrl)
  );
  if (!response.ok) {
    throw new Error(
      response.status === 404
        ? `brand kit ${brandKitId} was not found`
        : `brand kit fetch failed (HTTP ${response.status})`
    );
  }
  const payload = (await response.json()) as {
    brand_kit?: unknown;
    brand_kit_json?: unknown;
    brand_summary?: unknown;
    diagnostics?: unknown;
  };
  return {
    brandKit: toListEntry(payload.brand_kit),
    kitJson: payload.brand_kit_json ?? {},
    summary: payload.brand_summary ?? {},
    diagnostics: toDiagnostics(payload.diagnostics)
  };
}

/** Flip a kit's approval (`POST /brand-kits/{id}/approval`) and return the
 * refreshed detail. The pill flip is optimistic in the page; this call is the
 * confirmation the page reconciles against. */
export async function setBrandKitApproval(
  { apiBaseUrl, fetchImpl = fetch }: BrandHubOptions,
  brandKitId: string,
  approvalStatus: "approved" | "draft"
): Promise<BrandKitDetail> {
  const response = await fetchImpl(
    new URL(`/brand-kits/${encodeURIComponent(brandKitId)}/approval`, apiBaseUrl),
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ approval_status: approvalStatus })
    }
  );
  if (!response.ok) {
    throw new Error(`brand kit approval failed (HTTP ${response.status})`);
  }
  const payload = (await response.json()) as {
    brand_kit?: unknown;
    brand_kit_json?: unknown;
    brand_summary?: unknown;
    diagnostics?: unknown;
  };
  return {
    brandKit: toListEntry(payload.brand_kit),
    kitJson: payload.brand_kit_json ?? {},
    summary: payload.brand_summary ?? {},
    diagnostics: toDiagnostics(payload.diagnostics)
  };
}

/** The raw-bytes URL for an asset (`{base}/assets/{id}/bytes`) — the src for
 * logo/image thumbnails on the review page. */
export function assetBytesUrl(apiBaseUrl: string, assetId: string): string {
  return new URL(`/assets/${encodeURIComponent(assetId)}/bytes`, apiBaseUrl).toString();
}
