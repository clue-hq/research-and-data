import assert from "node:assert/strict";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { useSiteEditorOrigin, type SiteEditorOrigin } from "./use-site-editor-origin";

// Review finding K3-4: the editor's address was cached once for the whole browser page, with no
// workspace in the key, and switching workspace is a soft navigation — so after a switch, sites
// opened on the PREVIOUS workspace's editor domain (agent sections then failed to load, and the new
// workspace's site and brand were sent to an address meant for the old one). The address is now read
// per mount of the editor; a switch re-enters the app at its home, which unmounts every editor.
test("K3-4: after a workspace switch, the next editor reads the new workspace's address", async () => {
  const dom = new JSDOM("<div id='root'></div>", { url: "http://localhost:3029/" });
  for (const [key, value] of Object.entries({ window: dom.window, document: dom.window.document, IS_REACT_ACT_ENVIRONMENT: true })) {
    Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
  }
  let workspace = "aaa";
  let reads = 0;
  Object.defineProperty(globalThis, "fetch", {
    configurable: true,
    writable: true,
    value: async () => {
      reads += 1;
      return new Response(JSON.stringify({ data: { editorOrigin: `https://${workspace}.editor.example.com` } }), { status: 200 });
    },
  });
  const seen: SiteEditorOrigin[] = [];
  function Probe() {
    seen.push(useSiteEditorOrigin(true));
    return null;
  }
  const settle = async () => {
    for (let i = 0; i < 5; i += 1) await act(async () => new Promise((resolve) => setTimeout(resolve, 1)));
  };
  let root = createRoot(dom.window.document.getElementById("root")!);
  await act(async () => root.render(createElement(Probe)));
  await settle();
  assert.equal(seen.at(-1)?.origin, "https://aaa.editor.example.com");
  await act(async () => root.unmount());

  workspace = "bbb"; // the switch: a new cookie, the app re-entered at its home
  root = createRoot(dom.window.document.getElementById("root")!);
  await act(async () => root.render(createElement(Probe)));
  await settle();
  assert.equal(seen.at(-1)?.origin, "https://bbb.editor.example.com", "the new workspace's editor");
  assert.equal(reads, 2);
  await act(async () => root.unmount());
});
