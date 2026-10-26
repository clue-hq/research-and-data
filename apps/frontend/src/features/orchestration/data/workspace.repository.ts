import { createBrowserRecordStore } from "@/features/preview/data/browser-record-store";
import { assignAccountOwners, WorkspaceSchema, type AccountRevision, type WorkspaceState } from "../model/workspace";
import { createWorkspaceFixture, parseWorkspace } from "./workspace.fixture";

export interface WorkspaceRepository {
  read():Promise<WorkspaceState>;
  assignOwners(items:AccountRevision[],ownerId:string):Promise<WorkspaceState>;
  subscribe(listener:() => void):() => void;
}
type Store = { read():Promise<WorkspaceState>; transact<R>(change:(state:WorkspaceState) => { state:WorkspaceState;result:R }):Promise<R> };
const EVENT = "clue-orchestration-v2";
export function createWorkspaceRepository(store:Store = createBrowserRecordStore("clue-orchestration-preview-v2",parseWorkspace,createWorkspaceFixture)):WorkspaceRepository {
  return {
    read:() => store.read(),
    async assignOwners(items,ownerId) {
      const state = await store.transact((s) => { const state = WorkspaceSchema.parse(assignAccountOwners(s,items,ownerId)); return {state,result:state}; });
      if (typeof window !== "undefined") {
        window.dispatchEvent(new Event(EVENT));
        if (typeof BroadcastChannel !== "undefined") { const channel = new BroadcastChannel(EVENT);channel.postMessage("changed");channel.close(); }
      }
      return state;
    },
    subscribe(listener) {
      if (typeof window === "undefined") return () => {};
      window.addEventListener(EVENT,listener);
      const channel = typeof BroadcastChannel === "undefined" ? null : new BroadcastChannel(EVENT);
      if (channel) channel.onmessage = listener;
      return () => { window.removeEventListener(EVENT,listener);channel?.close(); };
    },
  };
}
