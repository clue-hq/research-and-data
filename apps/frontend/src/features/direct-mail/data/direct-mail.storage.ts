import { StateSchema, type DirectMailState } from "../model/direct-mail";
import { createDirectMailFixture } from "./direct-mail.fixture";

export interface DirectMailStore {
  read(): Promise<DirectMailState>;
  transact<T>(change: (state: DirectMailState) => { state: DirectMailState; result: T }): Promise<T>;
}

/** One atomic workspace record: concurrent tabs cannot approve an outdated draft. */
export function createBrowserDirectMailStore(): DirectMailStore {
  let database: Promise<IDBDatabase> | undefined;
  const open = () => database ??= new Promise((resolve, reject) => {
    const request = indexedDB.open("clue-direct-mail-preview-v1", 1);
    request.onupgradeneeded = () => request.result.createObjectStore("workspace");
    request.onsuccess = () => { request.result.onversionchange = () => request.result.close(); resolve(request.result); };
    request.onerror = () => { database = undefined; reject(new Error("Local drafts could not be opened. Check browser storage permissions and try again.")); };
    request.onblocked = () => { database = undefined; reject(new Error("Close other preview tabs and try again.")); };
  });
  const transact: DirectMailStore["transact"] = async (change) => {
    const db = await open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction("workspace", "readwrite");
      const store = tx.objectStore("workspace");
      const request = store.get("state");
      let result: ReturnType<typeof change>["result"];
      let failure: unknown;
      request.onsuccess = () => {
        try {
          const next = change(StateSchema.parse(request.result ?? createDirectMailFixture()));
          store.put(StateSchema.parse(next.state), "state"); result = next.result;
        } catch (error) { failure = error; tx.abort(); }
      };
      tx.oncomplete = () => resolve(result);
      tx.onerror = tx.onabort = () => reject(failure ?? new Error("Your changes could not be saved locally. Try a smaller file or free browser storage, then retry."));
    });
  };
  return { transact, read: () => transact((state) => ({ state, result: state })) };
}
