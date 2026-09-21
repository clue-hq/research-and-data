import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";
import { browserAssetRepository, fixtureAssetRepository, type AssetPatch } from "../data/asset.repository";
import { createAssetUploadQueue } from "../model/asset-upload-queue";
import type { AssetContext, AssetUploadCapabilities } from "../model/asset-context";
import type { BrandAsset } from "../model/brand-context";

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
  const [saving, setSaving] = useState(false);
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
          setMetadata(prior => ({...prior, ...result}));
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
    setMetadata(prior => ({...prior, ...result}));
    queue.setMetadata(result);
    router.refresh();
  }
  async function save(id: string, patch: AssetPatch) {
    if (!canWrite) {setError("You do not have permission to edit assets."); return false;}
    setSaving(true); setError(null);
    try { await repository.save(id, patch); await refresh(id); return true; }
    catch (err) {setError(err instanceof Error ? err.message : "Could not save asset"); return false;}
    finally {setSaving(false);}
  }
  async function retry(id: string) {
    if (!canWrite) {setError("You do not have permission to analyze assets."); return;}
    setError(null);
    try { await repository.retry(id); await refresh(id); }
    catch (err) {setError(err instanceof Error ? err.message : "Could not retry analysis");}
  }
  const enriched = assets.map(asset => {
    const context = metadata[asset.id] ?? asset.context;
    return context ? {...asset, context, name: context.title ?? asset.name, description: context.description ?? asset.description,
      sources: context.source_occurrences.length ? [...new Set(context.source_occurrences.map(occurrence => occurrence.source))] : asset.sources} : asset;
  });
  return {assets: enriched, queue, uploads, open, setOpen, error, saving, save, retry, limits, canWrite};
}
