import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "jsdom";
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { HARVESTED_AD_PAGE, AD_PAGE_ID } from "../adapter/__fixtures__/scene-nodes";
import { vi } from "../engine/__tests__/vitest-shim";
import type { Scene } from "../engine/scene/contracts";
import type { BrandKitDetailPayload } from "../engine/scene/tokenColors";
import type { SceneEditingSession } from "./use-scene-editing-session";

const pending = new Map<string, (kit: BrandKitDetailPayload) => void>();
// Only the transport boundaries are replaced. Exercise the real session,
// hydration, controller and mounted inspector while kit responses are delayed.
vi.mock(require.resolve("../engine/scene/documentStore"), (original) => ({
  ...original,
  fetchBrandKitDetail: (_config: unknown, id: string, version: number) =>
    new Promise<BrandKitDetailPayload>((resolve) => pending.set(`${id}@${version}`, resolve)),
}));
vi.mock(require.resolve("../engine/scene/libraryFonts"), (original) => ({
  ...original,
  fetchFontLibrary: async () => ({ version: 1, families: [] }),
}));

function kit(family: string, size: number): BrandKitDetailPayload {
  const tokens = { colors: {}, typography: { "type.headline": { value: { default: {
    kind: "style", font_family: family, font_size: size, font_weight: 500,
  } } } } };
  return { tokens };
}

function scene(kitId: string, version: number): Scene {
  const value = structuredClone(HARVESTED_AD_PAGE);
  value.meta.brand_kit = { id: kitId, version };
  const node = value.nodes.text_headline;
  if (node.kind.kind !== "text") throw new Error("expected text");
  node.kind = { ...node.kind, font_family: "Inter", font_size: 16,
    font_weight: 400, style_token: "type.headline", font_size_token: null,
    line_height_token: null, letter_spacing_token: null };
  return value;
}

test("mounted inspector waits for the pinned typography, rehydrates on arrival, and rejects stale kit responses", async () => {
  const dom = new JSDOM("<div id='root'></div>", { url: "http://localhost:3021" });
  dom.window.HTMLElement.prototype.scrollIntoView = () => {};
  const originals = new Map<string, PropertyDescriptor | undefined>();
  for (const [key, value] of Object.entries({
    window: dom.window, document: dom.window.document, navigator: dom.window.navigator,
    HTMLElement: dom.window.HTMLElement, Element: dom.window.Element,
    Node: dom.window.Node, getComputedStyle: dom.window.getComputedStyle,
    ResizeObserver: class { observe() {} unobserve() {} disconnect() {} },
    requestAnimationFrame: (): number => 1, cancelAnimationFrame() {},
    IS_REACT_ACT_ENVIRONMENT: true,
  })) {
    originals.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
    Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
  }
  // Base UI chooses its external-store implementation at import time; import
  // the real UI only after the DOM exists, as it does in a browser bundle.
  const previousCssLoader = require.extensions[".css"];
  require.extensions[".css"] = (module) => { module.exports = {}; };
  let useSceneEditingSession: typeof import("./use-scene-editing-session").useSceneEditingSession;
  let ImageInspector: typeof import("../../chat-shell/components/image-inspector").ImageInspector;
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports -- Load after the transport mocks and DOM setup.
    ({ useSceneEditingSession } = require("./use-scene-editing-session"));
    // eslint-disable-next-line @typescript-eslint/no-require-imports -- Node has no CSS module loader.
    ({ ImageInspector } = require("../../chat-shell/components/image-inspector"));
  } finally {
    if (previousCssLoader) require.extensions[".css"] = previousCssLoader;
    else delete require.extensions[".css"];
  }
  let session!: SceneEditingSession;
  function Harness({ documentId }: { documentId: string }) {
    session = useSceneEditingSession({ activeArtifactId: "artifact", documentIds: { artifact: documentId } });
    return createElement(ImageInspector, { selection: "text", onSelectionChange() {},
      hydrated: session.hydrated ?? undefined,
      fontOptions: ["Inter", "Season Mix", "Brand B", "Late Brand"] });
  }
  const root = createRoot(dom.window.document.getElementById("root")!);
  const size = () => dom.window.document.querySelector<HTMLInputElement>("[aria-label='Font size']")!;
  const family = () => dom.window.document.querySelector<HTMLButtonElement>("[aria-label='Font family']")!;
  // Founder 2026-10-19: text is edited on the canvas, so the ad text inspector has no Text field.
  const content = () => dom.window.document.querySelector<HTMLTextAreaElement>("[aria-label='Text content']");
  const load = async (documentId: string, value: Scene) => {
    await act(async () => root.render(createElement(Harness, { documentId })));
    await act(async () => {
      session.onSceneChange(value, AD_PAGE_ID, documentId);
      session.onSelectLayer("text_headline");
    });
  };
  try {
    const first = scene("brand_a", 1);
    await load("doc_a", first);
    assert.equal(size().disabled, true);
    assert.equal(size().value, "");
    assert.equal(family().disabled, true);
    assert.equal(content() === null, true, "the ad text inspector has no Text field");
    assert.match(dom.window.document.body.textContent ?? "", /Brand typography is unavailable/);
    assert.ok(pending.has("brand_a@1"));
    await act(async () => pending.get("brand_a@1")!(kit("Season Mix", 67.5)));
    assert.equal(session.scene, first, "the same scene object rehydrates when its kit arrives");
    assert.equal(size().disabled, false);
    assert.equal(size().value, "67.5");
    assert.equal(session.hydrated?.fontFamily, "Season Mix");
    assert.match(family().textContent ?? "", /Season Mix/, family().outerHTML);
    assert.doesNotMatch(dom.window.document.body.textContent ?? "", /Brand typography is unavailable/);

    await load("doc_a2", scene("brand_a", 2));
    assert.equal(size().disabled, true, "a new pinned version cannot use the old kit");
    await load("doc_b", scene("brand_b", 1));
    assert.equal(size().value, "");
    await act(async () => pending.get("brand_b@1")!(kit("Brand B", 48)));
    assert.equal(size().value, "48");
    assert.match(family().textContent ?? "", /Brand B/);
    await act(async () => pending.get("brand_a@2")!(kit("Late Brand", 96)));
    assert.equal(size().value, "48", "a late previous-document response is ignored");
    assert.match(family().textContent ?? "", /Brand B/);

    const incomplete = kit("Brand B", 48);
    incomplete.tokens = { colors: {} };
    await load("doc_c", scene("brand_c", 1));
    await act(async () => pending.get("brand_c@1")!(incomplete));
    assert.equal(size().disabled, true, "a missing role stays unavailable after the fetch settles");
    assert.equal(content() === null, true, "the ad text inspector has no Text field");
  } finally {
    await act(async () => root.unmount());
    pending.clear();
    dom.window.close();
    for (const [key, descriptor] of originals) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else Reflect.deleteProperty(globalThis, key);
    }
  }
});
