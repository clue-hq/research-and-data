import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "jsdom";
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { vi } from "../engine/__tests__/vitest-shim";
import { HARVESTED_AD_PAGE } from "../adapter/__fixtures__/scene-nodes";
import type { Scene } from "../engine/scene/contracts";
import type { LoadedDocument } from "../engine/scene/documentStore";
import type { WasmEngine, WasmModule } from "../engine/scene/wasmEngine";
import type { RenderContext } from "../engine/scene/renderContext";
import type { SceneDocumentState } from "./use-scene-document";

const requests: Array<{ id:string; resolve:(value:LoadedDocument)=>void; reject:(error:Error)=>void }> = [];
const fonts: Array<{ resolve:(value:boolean)=>void; reject:(error:Error)=>void }> = [];
const canvas: Array<(value:unknown)=>void> = [];
const measured: WasmEngine[] = [];
class RawEngine {
  private scene: Scene;
  private context: RenderContext | null = null;
  constructor(value:string) { this.scene = JSON.parse(value); }
  sceneJson() { return JSON.stringify(this.scene); }
  presentationJson() { return JSON.stringify({ scene:this.scene, context_key:this.context?.context_key,
    input_revision:1, status:this.context ? "ready" : "pending", diagnostics:[{ severity:"warning", phase:"layout",
      code:"TEST_RENDER_DIAGNOSTIC", message:"Review the rendered geometry." }] }); }
  setRenderContext(value:string) { this.context = JSON.parse(value); return this.presentationJson(); }
}
vi.mock(require.resolve("../engine/scene/wasmEngine"), original => ({ ...original,
  activateWasmCore: async () => ({ status:"active", module:{ LumenEngine:RawEngine,
    engineVersion:()=>"{}" } as unknown as WasmModule }),
}));
vi.mock(require.resolve("../engine/scene/documentStore"), original => ({ ...original,
  fetchDocument: (_config:unknown,id:string) => new Promise<LoadedDocument>((resolve,reject) => requests.push({id,resolve,reject})),
}));
vi.mock(require.resolve("../engine/scene/kitFonts"), original => ({ ...original,
  loadKitFontFaces: () => new Promise<boolean>((resolve,reject)=>fonts.push({resolve,reject})),
}));
vi.mock(require.resolve("../engine/scene/libraryFonts"), original => ({ ...original, loadLibraryFontFaces:async()=>false }));
vi.mock(require.resolve("../engine/scene/canvaskit/loadCanvasKit"), original => ({ ...original,
  loadCanvasKit: () => new Promise(resolve=>canvas.push(resolve)),
}));
vi.mock(require.resolve("../engine/scene/canvaskit/skiaMeasurements"), original => ({ ...original,
  injectSkiaMeasurements: (engine:WasmEngine) => { measured.push(engine); return { calls:0,converged:true,missing:[] }; },
}));
// eslint-disable-next-line @typescript-eslint/no-require-imports -- Load the real hook after transport and GPU boundaries are controlled.
const { useSceneDocument } = require("./use-scene-document") as typeof import("./use-scene-document");
function loaded(id:string,key:string):LoadedDocument {
  const scene = structuredClone(HARVESTED_AD_PAGE); scene.meta.id=id;
  const pin = {id:"same-kit",version:1}; scene.meta.brand_kit=pin;
  return { documentId:id, title:id, scene, currentVersion:1, undoDepth:0,redoDepth:0,
    agentInstructions:null, layoutManagedEditing:false, renderContext:{ context_key:key,
      document_id:id,document_version:1,scene_brand_ref:pin,scene_medium:scene.meta.medium,
      source:"document", brand_kit:{...pin,tokens:{}},mode:{values:{theme:key}},diagnostics:[] } };
}

test("fresh loads fence out-of-order success/failure, same-pin mode changes and stale font/measurement completion", async () => {
  const dom = new JSDOM("<div id='root'></div>");
  const saved = new Map<string,PropertyDescriptor|undefined>();
  for (const [key,value] of Object.entries({ window:dom.window,document:dom.window.document,
    navigator:dom.window.navigator,IS_REACT_ACT_ENVIRONMENT:true })) {
    saved.set(key,Object.getOwnPropertyDescriptor(globalThis,key));
    Object.defineProperty(globalThis,key,{configurable:true,writable:true,value});
  }
  let state:SceneDocumentState | null = null;
  function Probe({id,nonce}:{id:string;nonce:number}) { state=useSceneDocument(id,nonce); return null; }
  const root=createRoot(dom.window.document.getElementById("root")!);
  const render=async(id:string,nonce=0)=>act(async()=>{root.render(createElement(Probe,{id,nonce}));});
  const read=()=>{assert.ok(state);return state;};
  try {
    await render("A");
    await act(async()=>requests[0].resolve(loaded("A","light")));
    const first=read().engine!;
    assert.equal(first.derivation.context_key,"light");
    assert.equal(first.derivation.diagnostics[0].code,"TEST_RENDER_DIAGNOSTIC");
    assert.equal(read().fontDiagnostics.length,0, "render diagnostics must not be labeled as font failures");
    await render("B");
    await render("C");
    await act(async()=>requests[2].resolve(loaded("C","light")));
    const current=read().engine!;
    await act(async()=>requests[1].resolve(loaded("B","stale-success")));
    assert.equal(read().engine,current);
    await render("D");
    await render("C",1);
    await act(async()=>requests[4].resolve(loaded("C","dark")));
    const replacement=read().engine!;
    assert.notEqual(replacement,current);
    assert.equal(replacement.derivation.context_key,"dark");
    await act(async()=>requests[3].reject(new Error("stale fetch failure")));
    await act(async()=>{ fonts[0].reject(new Error("stale A font failure")); fonts[1].resolve(true); });
    assert.equal(read().engine,replacement);
    assert.equal(read().error,null);
    assert.equal(read().fontDiagnostics.length,0);
    await act(async()=>{ for(const resolve of canvas.splice(0)) resolve({ck:{},fontProvider:{}}); });
    assert.deepEqual(measured,[replacement]);
    assert.equal(read().presentationScene,replacement.presentationScene);
  } finally {
    await act(async()=>root.unmount()); dom.window.close();
    for(const [key,descriptor] of saved) {
      if(descriptor) Object.defineProperty(globalThis,key,descriptor);
      else Reflect.deleteProperty(globalThis,key);
    }
  }
});
