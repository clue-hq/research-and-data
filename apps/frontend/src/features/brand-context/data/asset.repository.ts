import { z } from "zod";
import { AssetContextBatchSchema, AssetContextSchema, AssetOverridesSchema, AssetUploadCapabilitiesSchema, type AssetUploadCapabilities, type AssetContext, type AssetOverrides } from "../model/asset-context";

export type AssetPatch = AssetOverrides & {reset_fields?: string[]};
export interface UploadAssetRequest { file: File; key: string; overrides: AssetOverrides; brandKitId?: string }
export interface AssetRepository {
  capabilities(): Promise<AssetUploadCapabilities>;
  upload(request: UploadAssetRequest): Promise<{assetId: string; context?: AssetContext}>;
  readMetadata(ids: string[]): Promise<Record<string, AssetContext>>;
  save(assetId: string, patch: AssetPatch): Promise<void>;
  retry(assetId: string): Promise<void>;
  /** Delete on the Assets page: archive the asset, so neither the page nor the design agent finds it. */
  archive(assetId: string): Promise<void>;
}
const UploadResponse = z.object({asset: z.object({id: z.string()}), enrichment: AssetContextSchema.nullish()});

export function httpAssetRepository(designFetch: () => Promise<typeof fetch> | typeof fetch): AssetRepository {
  async function request(path: string, init?: RequestInit) {
    const response = await (await designFetch())(path, {cache: "no-store", ...init});
    if (!response.ok) {
      let message = `Asset request failed (${response.status})`;
      try {
        const body = await response.json();
        if (typeof body.detail?.message === "string") message = body.detail.message;
        else if (typeof body.detail === "string") message = body.detail;
        else if (typeof body.error?.message === "string") message = body.error.message;
      } catch { /* Preserve a useful HTTP diagnostic for non-JSON failures. */ }
      throw new Error(message);
    }
    return response;
  }
  return {
    async capabilities() {return AssetUploadCapabilitiesSchema.parse(await (await request("/assets/upload-capabilities")).json());},
    async upload({file, key, overrides, brandKitId}) {
      const body = new FormData();
      body.set("file", file);
      const values = AssetOverridesSchema.parse(overrides);
      if (values.creative_type) body.set("creative_type", values.creative_type);
      if (values.usage_roles) body.set("usage_roles", JSON.stringify(values.usage_roles));
      if (values.user_note) body.set("user_note", values.user_note);
      if (brandKitId) body.set("brand_kit_id", brandKitId);
      const result = UploadResponse.parse(await (await request("/assets", {
        method: "POST", headers: {"Idempotency-Key": key}, body,
      })).json());
      return {assetId: result.asset.id, context: result.enrichment ?? undefined};
    },
    async readMetadata(ids) {
      const result: Record<string, AssetContext> = {};
      for (let offset = 0; offset < ids.length; offset += 100) {
        const query = new URLSearchParams({asset_ids: ids.slice(offset, offset + 100).join(",")});
        Object.assign(result, AssetContextBatchSchema.parse(await (await request(`/assets/descriptions?${query}`)).json()).descriptions);
      }
      return result;
    },
    async save(id, patch) {
      const values = AssetOverridesSchema.parse(patch);
      await request(`/assets/${encodeURIComponent(id)}/description`, {method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify({...values, reset_fields: patch.reset_fields})});
    },
    async retry(id) { await request(`/assets/${encodeURIComponent(id)}/analysis/retry`, {method: "POST"}); },
    async archive(id) { await request(`/assets/${encodeURIComponent(id)}/archive`, {method: "POST"}); },
  };
}

export function fixtureAssetRepository(): AssetRepository {
  const rows: Record<string, AssetContext> = {};
  const uploads = new Map<string, string>();
  return {
    async capabilities() {return {max_bytes: 10 * 1024 * 1024, formats: ["png", "jpeg", "webp", "svg", "gif"]};},
    async upload({key, file, overrides}) {
      const assetId = uploads.get(key) ?? `fixture-${key}`;
      uploads.set(key, assetId);
      rows[assetId] ??= AssetContextSchema.parse({asset_id: assetId, title: file.name, ...overrides, overrides, status: "stale"});
      return {assetId, context: rows[assetId]};
    },
    async archive(id) { delete rows[id]; },
    async readMetadata(ids) { return Object.fromEntries(ids.filter(id => rows[id]).map(id => [id, rows[id]])); },
    async save(id, patch) {
      const prior = rows[id] ?? AssetContextSchema.parse({asset_id: id});
      const overrides = {...prior.overrides, ...AssetOverridesSchema.parse(patch)};
      for (const field of patch.reset_fields ?? []) delete overrides[field as keyof AssetOverrides];
      const generated = prior.analysis ?? {};
      const effective = {...prior};
      for (const field of patch.reset_fields ?? []) {
        delete effective[field as keyof typeof effective];
      }
      rows[id] = AssetContextSchema.parse({...effective, ...generated, ...overrides, overrides, revision: prior.revision + 1});
    },
    async retry() { throw new Error("Automatic analysis requires a connected workspace."); },
  };
}

export function browserAssetRepository(workspaceId: string): AssetRepository {
  return httpAssetRepository(() => (input, init) => {
    const headers = new Headers(init?.headers);
    headers.set("X-Expected-Workspace-Id", workspaceId);
    return fetch(`/api/clue/design${input}`, {...init, headers});
  });
}
