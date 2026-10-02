import type { AssetPatch } from "../data/asset.repository";

export type AssetEditState = { patch: AssetPatch; saving: boolean; error: string | null; saved: boolean };
type Snapshot = Record<string, AssetEditState>;

/** Workspace-owned edits survive closing the inspector. Writes for each asset are ordered. */
export function createAssetEdits(persist: (id: string, patch: AssetPatch) => Promise<void>, delay = 500) {
  let snapshot: Snapshot = {};
  const listeners = new Set<() => void>();
  const timers = new Map<string, ReturnType<typeof setTimeout>>();
  const running = new Map<string, Promise<boolean>>();
  const revisions = new Map<string, number>();
  const publish = (id: string, state: AssetEditState) => {
    snapshot = { ...snapshot, [id]: state };
    listeners.forEach(listener => listener());
  };
  function stage(id: string, patch: AssetPatch) {
    clearTimeout(timers.get(id));
    const prior = snapshot[id] ?? { patch: {}, saving: false, error: null, saved: false };
    const merged = { ...prior.patch, ...patch };
    const resets = new Set(prior.patch.reset_fields ?? []);
    for (const field of patch.reset_fields ?? []) {
      delete merged[field as keyof AssetPatch];
      resets.add(field);
    }
    for (const field of Object.keys(patch)) if (field !== "reset_fields") resets.delete(field);
    if (resets.size) merged.reset_fields = [...resets];
    else delete merged.reset_fields;
    revisions.set(id, (revisions.get(id) ?? 0) + 1);
    publish(id, { ...prior, patch: merged, error: null, saved: false });
    timers.set(id, setTimeout(() => { void flush(id); }, delay));
  }
  async function flush(id: string): Promise<boolean> {
    clearTimeout(timers.get(id));
    timers.delete(id);
    const active = running.get(id);
    if (active) return active;
    if (!Object.keys(snapshot[id]?.patch ?? {}).length) return true;
    const task = (async () => {
      while (Object.keys(snapshot[id].patch).length) {
        const patch = snapshot[id].patch;
        const revision = revisions.get(id);
        publish(id, { ...snapshot[id], saving: true, error: null });
        try {
          await persist(id, patch);
        } catch (error) {
          publish(id, { ...snapshot[id], saving: false, error: error instanceof Error ? error.message : "Could not save changes." });
          return false;
        }
        // Keep newer edits (including a change back to an earlier value) until acknowledged.
        if (revision === revisions.get(id)) {
          publish(id, { patch: {}, saving: false, error: null, saved: true });
        }
      }
      return true;
    })();
    running.set(id, task);
    try { return await task; }
    finally { running.delete(id); }
  }
  return {
    subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; },
    getSnapshot: () => snapshot,
    stage,
    flush,
    async save(id: string, patch: AssetPatch) { stage(id, patch); return flush(id); },
  };
}
