import { withWalkthroughWorkspace } from "@/features/account-materials/data/walkthrough.fixture";
import { withMaterialsWorkspace } from "@/features/account-materials/data/materials.fixture";
import { createBrowserRecordStore } from "@/features/preview/data/browser-record-store";
import { approveArtifactContent, assignAccountOwners, WorkspaceSchema, type AccountRevision, type WorkspaceState } from "../model/workspace";
import { createWorkspaceFixture, parseWorkspace } from "./workspace.fixture";

export interface WorkspaceRepository {
  read():Promise<WorkspaceState>;
  assignOwners(items:AccountRevision[],ownerId:string):Promise<WorkspaceState>;
  approveContent(id:string,version:number):Promise<WorkspaceState>;
  subscribe(listener:() => void):() => void;
}
type Store = { read():Promise<WorkspaceState>; transact<R>(change:(state:WorkspaceState) => { state:WorkspaceState;result:R }):Promise<R> };
const EVENT = "clue-orchestration-v2";
export function createWorkspaceRepository(store:Store = createBrowserRecordStore("clue-orchestration-preview-v2",(value) => withWalkthroughWorkspace(withMaterialsWorkspace(parseWorkspace(value))),() => withWalkthroughWorkspace(withMaterialsWorkspace(createWorkspaceFixture())))):WorkspaceRepository {
  async function mutate(change:(s:WorkspaceState)=>WorkspaceState) {
    const state=await store.transact(s=>{const state=WorkspaceSchema.parse(change(s));return {state,result:state};});
    if(typeof window!=="undefined") {
      window.dispatchEvent(new Event(EVENT));
      if(typeof BroadcastChannel!=="undefined") {const channel=new BroadcastChannel(EVENT);channel.postMessage("changed");channel.close();}
    }
    return state;
  }
  return {
    read:()=>store.read(),
    assignOwners:(items,ownerId)=>mutate(s=>assignAccountOwners(s,items,ownerId)),
    approveContent:(id,version)=>mutate(s=>approveArtifactContent(s,id,version)),
    subscribe(listener) {
      if (typeof window === "undefined") return () => {};
      window.addEventListener(EVENT,listener);
      const channel = typeof BroadcastChannel === "undefined" ? null : new BroadcastChannel(EVENT);
      if (channel) channel.onmessage = listener;
      return () => { window.removeEventListener(EVENT,listener);channel?.close(); };
    },
  };
}
