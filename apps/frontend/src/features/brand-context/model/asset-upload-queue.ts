import type { AssetRepository, UploadAssetRequest } from "../data/asset.repository";
import { ASSET_UPLOAD_ACCEPT, ASSET_UPLOAD_TYPES, type AssetContext, type AssetOverrides } from "./asset-context";

export type UploadRow = UploadAssetRequest & {
  id: string; name: string; state: "selected" | "queued" | "uploading" | "uploaded" | "failed";
  retryable?: boolean;
  selected: boolean;
  assetId?: string; context?: AssetContext; error?: string;
};

/** Screen-owned queue. Closing its dialog affects visibility only. */
export function createAssetUploadQueue(repository: AssetRepository, onUploaded: () => void, concurrency = 3, refreshIntervalMs = 0) {
  let rows: UploadRow[] = [];
  let active = 0;
  let maxBytes = 10 * 1024 * 1024;
  let refreshTimer: ReturnType<typeof setTimeout> | undefined;
  function notifyUpload() {
    if (!refreshIntervalMs) {onUploaded(); return;}
    if (refreshTimer) return;
    refreshTimer = setTimeout(() => {refreshTimer = undefined; onUploaded();}, refreshIntervalMs);
  }
  const pending = new Set<string>();
  const listeners = new Set<() => void>();
  function emit() { for (const listener of listeners) listener(); }
  function update(id: string, patch: Partial<UploadRow>) {
    rows = rows.map(row => row.id === id ? {...row, ...patch} : row); emit();
  }
  function pump() {
    while (active < concurrency && pending.size) {
      const id = pending.values().next().value!;
      pending.delete(id);
      const row = rows.find(item => item.id === id);
      if (!row || row.state === "uploaded" || row.state === "uploading") continue;
      active++;
      update(id, {state: "uploading", error: undefined});
      void repository.upload(row).then(result => {
        update(id, {state: "uploaded", assetId: result.assetId, context: result.context});
        notifyUpload();
      }, error => update(id, {state: "failed", error: error instanceof Error ? error.message : "Upload failed"}))
        .finally(() => { active--; pump(); });
    }
  }
  return {
    subscribe(listener: () => void) { listeners.add(listener); return () => {listeners.delete(listener);}; },
    getSnapshot: () => rows,
    setMaxBytes(value: number) {maxBytes = value;},
    select(id: string, selected: boolean) {
      if (rows.find(row => row.id === id)?.state === "selected") update(id, {selected});
    },
    add(files: File[]) {
      rows = [...rows, ...files.map(file => {
        const id = crypto.randomUUID();
        const supported = ASSET_UPLOAD_TYPES.includes(file.type) || ASSET_UPLOAD_ACCEPT.split(",").some(ext => file.name.toLowerCase().endsWith(ext));
        const tooLarge = file.size > maxBytes;
        return {id, key: id, file, name: file.name, selected: true, overrides: {}, retryable: supported && !tooLarge, state: supported && !tooLarge ? "selected" as const : "failed" as const,
          error: tooLarge ? `File exceeds the ${maxBytes.toLocaleString()} byte upload limit.` : supported ? undefined : "Unsupported format. Choose PNG, JPEG, WebP, SVG or GIF."};
      })]; emit();
    },
    edit(id: string, patch: AssetOverrides) {
      const row = rows.find(item => item.id === id);
      if (row?.state === "selected" && !pending.has(id)) update(id, {overrides: {...row.overrides, ...patch}});
    },
    editAll(patch: AssetOverrides) {
      rows = rows.map(row => row.state === "selected" && row.selected && !pending.has(row.id) ? {...row, overrides: {...row.overrides, ...patch}} : row); emit();
    },
    start() {
      rows = rows.map(row => {
        if (row.state !== "selected" || !row.selected) return row;
        pending.add(row.id);
        return {...row, state: "queued"};
      });
      emit(); pump();
    },
    retry(id: string) {
      const row = rows.find(item => item.id === id);
      if (row?.state === "failed" && row.retryable) { pending.add(id); update(id, {state: "queued"}); pump(); }
    },
    setMetadata(contexts: Record<string, AssetContext>) {
      let changed = false;
      rows = rows.map(row => row.assetId && contexts[row.assetId] ? (changed = true, {...row, context: contexts[row.assetId]}) : row);
      if (changed) emit();
    },
  };
}
