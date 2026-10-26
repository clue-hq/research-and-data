/** Atomic browser records for isolated previews. Never used as a live backend. */
export function createBrowserRecordStore<T>(name: string, parse: (value: unknown) => T, seed: () => T) {
  let database: Promise<IDBDatabase> | undefined;
  const open = () => database ??= new Promise((resolve, reject) => {
    const request = indexedDB.open(name, 1);
    request.onupgradeneeded = () => request.result.createObjectStore("workspace");
    request.onsuccess = () => { request.result.onversionchange = () => request.result.close(); resolve(request.result); };
    request.onerror = () => { database = undefined; reject(new Error("Local drafts could not be opened. Check browser storage permissions and try again.")); };
    request.onblocked = () => { database = undefined; reject(new Error("Close other preview tabs and try again.")); };
  });
  async function transact<R>(change: (state: T) => { state: T; result: R }): Promise<R> {
    const db = await open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction("workspace", "readwrite"), store = tx.objectStore("workspace"), request = store.get("state");
      let result: R, failure: unknown;
      request.onsuccess = () => { try { const next = change(parse(request.result ?? seed())); store.put(parse(next.state), "state"); result = next.result; } catch (error) { failure = error; tx.abort(); } };
      tx.oncomplete = () => resolve(result);
      tx.onerror = tx.onabort = () => reject(failure ?? new Error("Your changes could not be saved locally. Check browser storage and retry."));
    });
  }
  return { transact, read: () => transact((state) => ({ state, result: state })) };
}
