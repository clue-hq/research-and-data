import assert from "node:assert/strict";
import { test } from "node:test";
import { SiteDocumentSchema } from "@clue/site-kit/site-document";
import { EDITOR_DID_NOT_ANSWER, EDITOR_NOT_CONFIGURED, siteCanvasState, type SiteCanvasInputs } from "./site-canvas-state";
import { siteStageMounted } from "./site-stage";

const filled = SiteDocumentSchema.parse({
  id: "doc-a",
  title: "A",
  theme: {},
  pages: { "/": { root: { props: {} }, content: [{ type: "CtaBand", props: { id: "cta" } }] } },
  shell: null,
  agent_sections: {},
});
const empty = { ...filled, pages: { "/": { root: { props: {} }, content: [] } } };
const READY: SiteCanvasInputs = {
  documentId: "doc-a",
  editorOrigin: "http://aac8c47153e8e006ea26797aa03615b6.editor.localhost:3129",
  editorOriginError: null,
  editorOriginLoaded: true,
  frameError: null,
  frameReady: true,
  frameTimedOut: false,
  loadError: null,
  loadStatus: "ready",
  shownDocumentId: "doc-a",
  site: filled,
};

test("the canvas is ready only when the frame shows THIS document", () => {
  assert.deepEqual(siteCanvasState(READY), { kind: "ready", message: null });
  assert.equal(siteCanvasState({ ...READY, shownDocumentId: "doc-b" }).kind, "loading");
  assert.equal(siteCanvasState({ ...READY, frameReady: false }).kind, "loading");
  assert.equal(siteCanvasState({ ...READY, loadStatus: "loading" }).kind, "loading");
});

test("no document is the empty state; a site with no sections yet is the empty state too", () => {
  assert.equal(siteCanvasState({ ...READY, documentId: null }).kind, "empty");
  assert.equal(siteCanvasState({ ...READY, frameReady: false, site: empty }).kind, "empty");
});

test("an unconfigured editor domain, a failed load or a frame error is the error state with its words", () => {
  assert.deepEqual(siteCanvasState({ ...READY, editorOrigin: null }), { kind: "error", message: EDITOR_NOT_CONFIGURED });
  assert.deepEqual(siteCanvasState({ ...READY, editorOrigin: null, editorOriginError: "HTTP 401" }), { kind: "error", message: "HTTP 401" });
  assert.deepEqual(siteCanvasState({ ...READY, loadError: "No such website.", loadStatus: "error" }), {
    kind: "error",
    message: "No such website.",
  });
  assert.deepEqual(siteCanvasState({ ...READY, frameError: "The section AnalysisSteps could not be loaded" }), {
    kind: "error",
    message: "The section AnalysisSteps could not be loaded",
  });
});

test("the frame is mounted for an open site, and kept warm only once an editor origin exists", () => {
  assert.equal(siteStageMounted({ editorOrigin: null, enabled: true, warm: false }), true, "an open site shows its states even unconfigured");
  assert.equal(siteStageMounted({ editorOrigin: null, enabled: false, warm: true }), false);
  assert.equal(siteStageMounted({ editorOrigin: "http://x.editor.localhost:3129", enabled: false, warm: true }), true);
  assert.equal(siteStageMounted({ editorOrigin: "http://x.editor.localhost:3129", enabled: false, warm: false }), false);
});

// Review finding S7-2: an editor domain the editor service does not serve, an app origin it does not
// allow to frame it, or missing DNS left the canvas on its loading veil forever (the frame never says
// it is ready, and nothing else reports a failure). After the frame host's timeout it says so.
test("a frame that never answers is the error state, not an endless loading veil", () => {
  const waiting = { ...READY, frameReady: false, shownDocumentId: null };
  assert.equal(siteCanvasState(waiting).kind, "loading", "still within the wait");
  assert.deepEqual(siteCanvasState({ ...waiting, frameTimedOut: true }), { kind: "error", message: EDITOR_DID_NOT_ANSWER });
  assert.equal(siteCanvasState({ ...READY, frameTimedOut: false }).kind, "ready");
  assert.equal(siteCanvasState({ ...READY, editorOrigin: null, frameTimedOut: true }).message, EDITOR_NOT_CONFIGURED, "not configured says so first");
});

