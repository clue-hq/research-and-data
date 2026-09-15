import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "jsdom";
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import type { CanvasKit, Image } from "canvaskit-wasm";
import { HARVESTED_AD_PAGE } from "../adapter/__fixtures__/scene-nodes";
import { vi } from "../engine/__tests__/vitest-shim";
import { CanvasKitImageCache } from "../engine/scene/canvaskit/imageCache";
import type { Scene } from "../engine/scene/contracts";
import type { SceneDocumentState } from "../hooks/use-scene-document";

const ASSET_ID = "asset_ing_2b0928ca4f3a3c70";
const DIGEST = "2b0928ca4f3a3c70c5c2fed22996f0428da219c953a14e71567b73c1d8af937a";
let loadedScene: Scene;
let loadGeneration = 1;
const imageCaches: CanvasKitImageCache[] = [];
const decodedImage = { delete() {} } as Image;

// Exercise the mounted component and its real URL/cache path. The document
// loader and GPU are boundaries here; this is not a pixel or handshake test.
vi.mock(require.resolve("../hooks/use-scene-document"), () => ({
  useSceneDocument: (): SceneDocumentState => ({
    kind: "ready", scene: loadedScene, presentationScene: loadedScene, engine: null,
    pageId: Object.keys(loadedScene.pages)[0], title: "Ad", error: null,
    engineStatus: { engineDisabled: false, reason: null, detail: null },
    currentVersion: 1, undoDepth: 0, redoDepth: 0, loadGeneration,
    tokenGeneration: 0, fontDiagnostics: [], measurementIncomplete: false, refresh() {},
  }),
}));
vi.mock(require.resolve("../engine/scene/canvaskit/loadCanvasKit"), (original) => ({
  ...original,
  loadCanvasKit: async () => ({
    ck: {
      MakeWebGLCanvasSurface: () => null,
      MakeSWCanvasSurface: () => null,
      MakeImageFromEncoded: () => decodedImage,
    } as unknown as CanvasKit,
    fontProvider: null,
  }),
}));
vi.mock(require.resolve("../engine/scene/canvaskit/imageCache"), (original) => ({
  ...original,
  CanvasKitImageCache: class extends CanvasKitImageCache {
    constructor(...args: ConstructorParameters<typeof CanvasKitImageCache>) {
      super(...args);
      imageCaches.push(this);
    }
  },
}));

// Node has no CSS loader. Keep that adaptation local to the component import.
const previousCssLoader = require.extensions[".css"];
require.extensions[".css"] = (module) => { module.exports = {}; };
let SceneArtifactCanvas: typeof import("./scene-artifact-canvas").SceneArtifactCanvas;
try {
  // eslint-disable-next-line @typescript-eslint/no-require-imports -- Load after the module-boundary stubs above.
  ({ SceneArtifactCanvas } = require("./scene-artifact-canvas"));
} finally {
  if (previousCssLoader) require.extensions[".css"] = previousCssLoader;
  else delete require.extensions[".css"];
}

for (const source of ["streamed display", "loaded document", "published asset"] as const) {
  test(`the mounted canvas hydrates a newly available image from its ${source} without remounting`, async () => {
    const dom = new JSDOM("<div id='root'></div>");
    const originals = new Map<string, PropertyDescriptor | undefined>();
    for (const [key, value] of Object.entries({
      window: dom.window, document: dom.window.document,
      navigator: dom.window.navigator, IS_REACT_ACT_ENVIRONMENT: true,
      requestAnimationFrame: (): number => 1, cancelAnimationFrame: () => {},
    })) {
      originals.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
      Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
    }
    loadedScene = structuredClone(HARVESTED_AD_PAGE);
    loadGeneration = 1;
    if (source !== "published asset") delete loadedScene.assets[ASSET_ID];
    const originalScene = structuredClone(loadedScene);
    imageCaches.length = 0;
    const requests: string[] = [];
    let published = source !== "published asset";
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (url) => {
      requests.push(String(url));
      if (!published) return new Response(null, { status: 404 });
      return new Response(new Uint8Array([1, 2, 3]));
    };
    const root = createRoot(dom.window.document.getElementById("root")!);
    try {
      const render = async (displayScene: Scene | null) => {
        await act(async () => {
          root.render(createElement(SceneArtifactCanvas, {
            documentId: loadedScene.meta.id, displayScene, gestureDisabled: true,
          }));
        });
      };
      await render(null);
      const canvas = dom.window.document.querySelector("canvas");
      assert.ok(canvas);
      const cache = imageCaches[0];
      assert.ok(cache, "the mounted surface created its image cache");
      assert.equal(cache.get(ASSET_ID), null);
      await act(async () => { await new Promise<void>((resolve) => setImmediate(resolve)); });
      const url = `/api/clue/design-public/asset-store/${DIGEST}`;
      assert.deepEqual(requests, source === "published asset" ? [url] : [],
        "only a known digest may issue a request");

      if (source === "published asset") {
        await render(null);
        assert.equal(cache.get(ASSET_ID), null);
        assert.deepEqual(requests, [url], "ordinary redraws must not retry a 404");
        published = true;
        loadGeneration += 1; // The saved document has now been authoritatively reloaded.
      }

      if (source === "loaded document") loadedScene = structuredClone(HARVESTED_AD_PAGE);
      await render(source === "streamed display" ? structuredClone(HARVESTED_AD_PAGE) : null);
      assert.equal(dom.window.document.querySelector("canvas"), canvas);
      assert.deepEqual(imageCaches, [cache], "hydration reuses the failed-null cache entry");
      assert.equal(cache.get(ASSET_ID), null);
      await act(async () => { await new Promise<void>((resolve) => setImmediate(resolve)); });
      assert.deepEqual(requests, source === "published asset" ? [url, url] : [url]);
      assert.equal(cache.get(ASSET_ID), decodedImage);
      if (source === "streamed display") assert.deepEqual(loadedScene, originalScene);
    } finally {
      await act(async () => root.unmount());
      globalThis.fetch = originalFetch;
      for (const [key, descriptor] of originals) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor);
        else Reflect.deleteProperty(globalThis, key);
      }
      dom.window.close();
    }
  });
}
