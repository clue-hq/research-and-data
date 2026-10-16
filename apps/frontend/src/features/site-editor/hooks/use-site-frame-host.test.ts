import assert from "node:assert/strict";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { frameToApp } from "@clue/site-kit/editor-protocol";
import { useSiteFrameHost, type SiteFrameHost } from "./use-site-frame-host";

// Review finding S7-2: a frame that never answered left the canvas loading forever. The host now
// says when THIS frame (its own nonce: a different site gets a fresh frame) has not said `ready`
// within the wait.
const ORIGIN = "https://aac8c47153e8e006ea26797aa03615b6.edit.example.com";

test("S7-2: the frame host reports a frame that does not answer in time, per frame", async () => {
  const dom = new JSDOM("<div id='root'></div>", { url: "http://localhost:3029/" });
  for (const [key, value] of Object.entries({
    window: dom.window,
    document: dom.window.document,
    MessageEvent: dom.window.MessageEvent,
    IS_REACT_ACT_ENVIRONMENT: true,
  })) {
    Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
  }
  const seen: SiteFrameHost[] = [];
  let documentId = "doc-a";
  let iframe: HTMLIFrameElement | null = null;
  function Probe() {
    const host = useSiteFrameHost({ documentId, editorOrigin: ORIGIN, onMessage: () => undefined, readyTimeoutMs: 40 });
    seen.push(host);
    return createElement("iframe", {
      key: host.src ?? "none",
      ref: (element: HTMLIFrameElement | null) => {
        host.iframeRef.current = element;
        iframe = element;
      },
    });
  }
  const latest = () => seen.at(-1)!;
  const wait = async (ms: number) => act(async () => new Promise((resolve) => setTimeout(resolve, ms)));
  const root = createRoot(dom.window.document.getElementById("root")!);
  await act(async () => root.render(createElement(Probe)));
  assert.equal(latest().timedOut, false);
  await wait(80);
  assert.equal(latest().timedOut, true, "no `ready` within the wait");

  const nonce = new URL(latest().src!).hash.replace(/^#n=/, "");
  await act(async () => {
    dom.window.dispatchEvent(
      new dom.window.MessageEvent("message", { data: frameToApp("ready", {}, { documentId: "", nonce }), origin: ORIGIN, source: iframe!.contentWindow }),
    );
  });
  assert.equal(latest().timedOut, false, "a late answer clears it");

  documentId = "doc-b"; // a different site: a fresh frame, a fresh wait
  await act(async () => root.render(createElement(Probe)));
  assert.equal(latest().timedOut, false);
  await wait(80);
  assert.equal(latest().timedOut, true);
  await act(async () => root.unmount());
});
