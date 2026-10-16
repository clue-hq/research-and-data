import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "jsdom";
import { act, createElement, StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { fixtureSiteRepository, SITE_FIXTURE_DOCUMENT_ID } from "../data/site.repository";
import { useSiteSaves } from "./use-site-saves";

function mountDom() {
  const dom = new JSDOM("<div id='root'></div>", { url: "http://localhost/" });
  for (const [key, value] of Object.entries({ window: dom.window, document: dom.window.document, IS_REACT_ACT_ENVIRONMENT: true })) {
    Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
  }
  return dom;
}

// Next's App Router turns StrictMode on in development: React then runs every effect's cleanup and
// the effect again on the same render's memoized objects. A controller disposed by that first
// cleanup silently dropped every site save on every dev stack (review finding S2b-2).
for (const strict of [false, true]) {
  test(`a save reaches the server${strict ? " under StrictMode" : ""}`, async () => {
    const dom = mountDom();
    const base = fixtureSiteRepository();
    const saved: number[] = [];
    const repository = {
      ...base,
      save: async (id: string, request: Parameters<typeof base.save>[1]) => {
        saved.push(request.baseVersion);
        return base.save(id, request);
      },
    };
    const seen: ReturnType<typeof useSiteSaves>[] = [];
    function Probe() {
      seen.push(useSiteSaves({ documentId: SITE_FIXTURE_DOCUMENT_ID, lockNote: "locked", onReload: () => undefined, repository }));
      return null;
    }
    const root = createRoot(dom.window.document.getElementById("root")!);
    await act(async () => root.render(strict ? createElement(StrictMode, null, createElement(Probe)) : createElement(Probe)));
    const loaded = await base.get(SITE_FIXTURE_DOCUMENT_ID);
    await act(async () => seen.at(-1)!.adopt(loaded));
    await act(async () => seen.at(-1)!.save({ ...loaded.site, title: "Edited title" }));
    await act(async () => new Promise((resolve) => setTimeout(resolve, 20)));
    assert.deepEqual(saved, [loaded.version]);
    assert.equal((await base.get(SITE_FIXTURE_DOCUMENT_ID)).site.title, "Edited title");
    assert.equal(seen.at(-1)!.baseVersion, loaded.version + 1);
    await act(async () => root.unmount());
  });
}
