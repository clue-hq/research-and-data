import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";
import { browserAssetRepository, fixtureAssetRepository, type AssetPatch } from "../data/asset.repository";
import { createAssetUploadQueue } from "../model/asset-upload-queue";
import { AssetContextSchema, type AssetContext, type AssetUploadCapabilities } from "../model/asset-context";
import type { BrandAsset } from "../model/brand-context";
import { createAssetEdits } from "../model/asset-edits";

function mergeMetadata(prior: Record<string, AssetContext>, incoming: Record<string, AssetContext>) {
  const next = {...prior};
  for (const [id, value] of Object.entries(incoming)) {
    if (!prior[id] || value.revision >= prior[id].revision) next[id] = value;
  }
  return next;
}

export function useAssetLibrary(assets: BrandAsset[], scopeKey: string, writable: boolean) {
  const router = useRouter();
  const connected = scopeKey !== "fixture";
  const canWrite = !connected || writable;
  const repository = useMemo(() => connected ? browserAssetRepository(scopeKey) : fixtureAssetRepository(), [connected, scopeKey]);
  const queue = useMemo(() => {
    // Each authenticated workspace owns its queue; a workspace switch cannot reuse upload keys.
    void scopeKey;
    return createAssetUploadQueue(repository, () => router.refresh(), 3, 750);
  }, [repository, router, scopeKey]);
  const uploads = useSyncExternalStore(queue.subscribe, queue.getSnapshot, queue.getSnapshot);
  const [open, setOpen] = useState(false);
  const [metadata, setMetadata] = useState<Record<string, AssetContext>>({});
  const [error, setError] = useState<string | null>(null);
  const edits = useMemo(() => createAssetEdits(async (id, patch) => {
    if (!canWrite) throw new Error("You do not have permission to edit assets.");
    await repository.save(id, patch);
    const result = await repository.readMetadata([id]);
    setMetadata(prior => mergeMetadata(prior, result));
    queue.setMetadata(result);
    router.refresh();
  }), [canWrite, repository, queue, router]);
  const editStates = useSyncExternalStore(edits.subscribe, edits.getSnapshot, edits.getSnapshot);
  const saving = Object.values(editStates).some(state => state.saving);
  const [limits, setLimits] = useState<AssetUploadCapabilities | null>(null);
  useEffect(() => {
    let disposed = false;
    void repository.capabilities().then(value => {
      if (!disposed) {queue.setMaxBytes(value.max_bytes); setLimits(value);}
    }, err => {if (!disposed) setError(err instanceof Error ? err.message : "Upload limits unavailable");});
    return () => {disposed = true;};
  }, [repository, queue]);
  const pendingIds = [...new Set([
    ...assets.filter(asset => ["queued", "analyzing"].includes((metadata[asset.id] ?? asset.context)?.status ?? "")).map(asset => asset.id),
    ...uploads.filter(row => row.assetId && ["queued", "analyzing"].includes(row.context?.status ?? "queued")).map(row => row.assetId!),
  ])].sort().join(",");
  useEffect(() => {
    if (!pendingIds) return;
    let disposed = false;
    let timeout: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const result = await repository.readMetadata(pendingIds.split(","));
        if (!disposed) {
          setMetadata(prior => mergeMetadata(prior, result));
          queue.setMetadata(result);
          setError(null);
        }
      } catch (err) { if (!disposed) setError(err instanceof Error ? err.message : "Analysis status unavailable"); }
      if (!disposed) timeout = setTimeout(poll, 2000);
    }
    timeout = setTimeout(poll, 1000);
    return () => {disposed = true; clearTimeout(timeout);};
  }, [pendingIds, queue, repository]);
  async function refresh(id: string) {
    const result = await repository.readMetadata([id]);
    setMetadata(prior => mergeMetadata(prior, result));
    queue.setMetadata(result);
    router.refresh();
  }
  async function save(id: string, patch: AssetPatch) {
    if (!canWrite) {setError("You do not have permission to edit assets."); return false;}
    return edits.save(id, patch);
  }
  async function remove(id: string) {
    if (!canWrite) {setError("You do not have permission to delete assets."); return false;}
    setError(null);
    try { await repository.archive(id); router.refresh(); return true; }
    catch (err) {setError(err instanceof Error ? err.message : "Could not delete the asset"); return false;}
  }
  async function retry(id: string) {
    if (!canWrite) {setError("You do not have permission to analyze assets."); return;}
    setError(null);
    try { await repository.retry(id); await refresh(id); }
    catch (err) {setError(err instanceof Error ? err.message : "Could not retry analysis");}
  }
  const enriched = assets.map(asset => {
    const cached = metadata[asset.id];
    const latest = asset.context && (!cached || asset.context.revision > cached.revision) ? asset.context : cached;
    const stored = latest ?? AssetContextSchema.parse({asset_id: asset.id, title: asset.name, description: asset.description});
    const patch = editStates[asset.id]?.patch;
    const values = Object.fromEntries(Object.entries(patch ?? {}).filter(([key, value]) => key !== "reset_fields" && value != null)) as Partial<AssetContext>;
    const context = {...stored, ...values};
    return {...asset, context, name: context.title ?? asset.name, description: context.description ?? asset.description,
      sources: context.source_occurrences.length ? [...new Set(context.source_occurrences.map(occurrence => occurrence.source))] : asset.sources};
  });
  return {assets: enriched, queue, uploads, open, setOpen, error, saving, save, retry, remove, limits, canWrite, edits, editStates};
}
