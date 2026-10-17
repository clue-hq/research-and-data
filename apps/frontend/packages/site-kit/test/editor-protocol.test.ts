import assert from "node:assert/strict";
import { test } from "node:test";
import type { BrandData } from "../src/brand";
import {
  EDITOR_PROTOCOL_VERSION,
  FieldDescriptionSchema,
  acceptAppMessage,
  acceptFrameMessage,
  appToFrame,
  frameToApp,
  parseAppToFrame,
  parseFrameToApp,
} from "../src/editor-protocol";
import { SiteDocumentSchema } from "../src/site-document";

const NONCE = "nonce-0123456789abcdef";
const APP = "http://localhost:3029";
const EDITOR = "http://aac8c47153e8e006ea26797aa03615b6.editor.localhost:3129";
const parentWindow = { name: "app window" };
const frameWindow = { name: "editor frame" };
const ctx = { documentId: "doc_1", nonce: NONCE };
const site = SiteDocumentSchema.parse({
  id: "doc_1",
  title: "New site",
  theme: {},
  pages: { "/": { root: { props: { title: "New site" } }, content: [] } },
  shell: null,
  agent_sections: {},
});
const brand = { slug: "x", measured: null, kit: {}, fonts: [], assets: {}, clones: {} } as unknown as BrandData;
const GEOMETRY = {
  viewport: { x: 0, y: 10, top: 10, right: 100, bottom: 60, left: 0, width: 100, height: 50 },
  document: { x: 0, y: 410, top: 410, right: 100, bottom: 460, left: 0, width: 100, height: 50 },
};

test("every app → frame message builds and parses with its envelope", () => {
  const init = appToFrame("init", { site, brand, sections: [], mode: "edit", route: "/", device: "Desktop", rev: 1 }, ctx);
  assert.equal(parseAppToFrame(JSON.parse(JSON.stringify(init)))?.type, "init");
  const messages = [
    appToFrame("replace_site", { site, rev: 3 }, ctx),
    appToFrame("set_mode", { mode: "preview" }, ctx),
    appToFrame("navigate", { route: "/" }, ctx),
    appToFrame("set_props", { route: "shell", componentId: "header", props: { preparedFor: "X" }, rev: 4 }, ctx),
    appToFrame("select", { route: "/", componentId: null }, ctx),
    appToFrame("insert_asset", { route: "/", componentId: "hero", prop: "image", url: `/asset-store/${"e".repeat(64)}`, rev: 5 }, ctx),
  ];
  for (const message of messages) assert.equal(parseAppToFrame(message)?.type, message.type);
});

test("every frame → app message parses, including the shell target and the shortcut addition", () => {
  const messages = [
    frameToApp("ready", {}, { documentId: "", nonce: NONCE }),
    frameToApp("changed", { site, baseRev: 2 }, ctx),
    frameToApp("selected", { route: "shell", componentId: "header", componentType: "SiteHeader", fields: [], props: {} }, ctx),
    frameToApp("deselected", {}, ctx),
    frameToApp("navigated", { route: "/" }, ctx),
    frameToApp("request_asset", { route: "/", componentId: "hero", prop: "image" }, ctx),
    frameToApp("annotate", { route: "/", componentId: "hero", geometry: GEOMETRY }, ctx),
    frameToApp("error", { code: "section_load_failed", message: "AnalysisSteps did not load" }, ctx),
    frameToApp("shortcut", { action: "undo" }, ctx),
    frameToApp("pending", { pending: true }, ctx),
    frameToApp("open_link", { href: "https://example.com/pricing" }, ctx),
  ];
  for (const message of messages) assert.equal(parseFrameToApp(message)?.type, message.type);
});

test("`pending` says only whether the frame holds work it has not sent yet", () => {
  const pending = frameToApp("pending", { pending: false }, ctx);
  assert.deepEqual(parseFrameToApp(pending)?.payload, { pending: false });
  assert.equal(parseFrameToApp({ ...pending, payload: { pending: "yes" } }), null);
  assert.equal(parseFrameToApp({ ...pending, payload: { pending: true, site: {} } }), null);
});

test("a message off the channel, the version or the schema is dropped", () => {
  const good = frameToApp("deselected", {}, ctx);
  assert.equal(parseFrameToApp({ ...good, channel: "lumen-web-bridge" }), null);
  assert.equal(parseFrameToApp({ ...good, v: 1 }), null);
  assert.equal(parseFrameToApp({ ...good, nonce: "short" }), null);
  assert.equal(parseFrameToApp({ ...good, type: "puck:publish" }), null);
  assert.equal(parseFrameToApp({ type: "puck:publish", headline: "x" }), null);
  const insert = appToFrame("insert_asset", { route: "/", componentId: "hero", prop: "image", url: `/asset-store/${"e".repeat(64)}`, rev: 5 }, ctx);
  assert.equal(parseAppToFrame({ ...insert, payload: { ...insert.payload, url: "https://evil.example/pixel.gif" } }), null);
  assert.equal(parseAppToFrame({ ...insert, payload: { ...insert.payload, componentId: "hero#1" } }), null);
});

test("the app accepts a frame message only from its own iframe, origin, nonce and document", () => {
  const expected = { documentId: "doc_1", editorOrigin: EDITOR, nonce: NONCE, source: frameWindow };
  const message = frameToApp("deselected", {}, ctx);
  assert.ok(acceptFrameMessage({ data: message, origin: EDITOR, source: frameWindow }, expected));
  assert.equal(acceptFrameMessage({ data: message, origin: "http://evil.editor.localhost:3129", source: frameWindow }, expected), null);
  assert.equal(acceptFrameMessage({ data: message, origin: EDITOR, source: { name: "another tab" } }, expected), null);
  assert.equal(
    acceptFrameMessage({ data: { ...message, nonce: "nonce-from-an-old-frame" }, origin: EDITOR, source: frameWindow }, expected),
    null,
  );
  assert.equal(acceptFrameMessage({ data: { ...message, documentId: "doc_old" }, origin: EDITOR, source: frameWindow }, expected), null);
  assert.equal(acceptFrameMessage({ data: message, origin: EDITOR, source: frameWindow }, { ...expected, editorOrigin: null }), null);
  // The D2 spike's ParentFrame probe: an agent section posting to its parent is not a protocol message.
  assert.equal(
    acceptFrameMessage({ data: { type: "puck:publish", headline: "x" }, origin: EDITOR, source: frameWindow }, expected),
    null,
  );
});

test("ready is accepted before any document is initialised, and only with an empty document id", () => {
  const expected = { documentId: null, editorOrigin: EDITOR, nonce: NONCE, source: frameWindow };
  const ready = frameToApp("ready", {}, { documentId: "", nonce: NONCE });
  assert.ok(acceptFrameMessage({ data: ready, origin: EDITOR, source: frameWindow }, expected));
  assert.equal(
    acceptFrameMessage({ data: frameToApp("ready", {}, ctx), origin: EDITOR, source: frameWindow }, expected),
    null,
  );
  assert.equal(
    acceptFrameMessage({ data: frameToApp("deselected", {}, ctx), origin: EDITOR, source: frameWindow }, expected),
    null,
  );
});

test("the frame accepts an app message only from its parent and the app origin; init names the document", () => {
  const expected = { appOrigin: APP, documentId: "", nonce: NONCE, parent: parentWindow };
  const init = appToFrame("init", { site, brand, sections: [], mode: "edit", route: "/", device: "Desktop", rev: 1 }, ctx);
  assert.ok(acceptAppMessage({ data: init, origin: APP, source: parentWindow }, expected));
  assert.equal(acceptAppMessage({ data: init, origin: "http://localhost:3030", source: parentWindow }, expected), null);
  assert.equal(acceptAppMessage({ data: init, origin: APP, source: { name: "an agent section's window" } }, expected), null);
  const mode = appToFrame("set_mode", { mode: "edit" }, ctx);
  assert.equal(acceptAppMessage({ data: mode, origin: APP, source: parentWindow }, expected), null, "no document yet");
  assert.ok(acceptAppMessage({ data: mode, origin: APP, source: parentWindow }, { ...expected, documentId: "doc_1" }));
  const unnamed = appToFrame("init", { site, brand, sections: [], mode: "edit", route: "/", device: "Desktop", rev: 1 }, { documentId: "", nonce: NONCE });
  assert.equal(acceptAppMessage({ data: unnamed, origin: APP, source: parentWindow }, expected), null);
});

test("field descriptions nest for lists and refuse unknown kinds", () => {
  const parsed = FieldDescriptionSchema.parse({
    kind: "list",
    label: "Stats",
    name: "stats",
    item: [{ kind: "text", label: "Value", name: "value" }],
  });
  assert.equal(parsed.item?.[0].kind, "text");
  assert.equal(FieldDescriptionSchema.safeParse({ kind: "html", label: "Stats", name: "stats" }).success, false);
});

// The sync fix (2026-10-14): every copy of the site the app sends carries a revision, and every
// canvas edit the frame proposes names the revision it started from, so the app can refuse an edit
// made over an older copy. A v1 peer (no revisions) is refused outright rather than half-understood.
test("v2: site messages carry revisions; a message without them, or from v1, is refused", () => {
  assert.equal(EDITOR_PROTOCOL_VERSION, 2);
  const changed = frameToApp("changed", { site, baseRev: 3 }, ctx);
  assert.ok(parseFrameToApp(changed));
  assert.equal(parseFrameToApp({ ...changed, payload: { site } }), null);
  assert.equal(parseFrameToApp({ ...changed, payload: { site, baseRev: -1 } }), null);
  const replace = appToFrame("replace_site", { site, rev: 4 }, ctx);
  assert.ok(parseAppToFrame(replace));
  assert.equal(parseAppToFrame({ ...replace, payload: { site, version: 4 } }), null);
  assert.equal(parseAppToFrame({ ...replace, v: 1 }), null);
  const init = appToFrame("init", { site, brand, sections: [], mode: "edit", route: "/", device: "Desktop", rev: 1 }, ctx);
  assert.equal(parseAppToFrame({ ...init, payload: { ...init.payload, rev: undefined } }), null);
  const patch = appToFrame("set_props", { route: "/", componentId: "hero", props: {}, rev: 6 }, ctx);
  assert.equal(parseAppToFrame({ ...patch, payload: { route: "/", componentId: "hero", props: {} } }), null);
});

test("`open_link` carries only an http(s) address", () => {
  const good = frameToApp("open_link", { href: "https://example.com/a?b=1" }, ctx);
  assert.equal(parseFrameToApp(good)?.type, "open_link");
  assert.equal(parseFrameToApp({ ...good, payload: { href: "http://example.com" } })?.type, "open_link");
  for (const href of ["javascript:alert(1)", "data:text/html,x", "/pricing", "mailto:a@b.co", "HTTPS:", ""]) {
    assert.equal(parseFrameToApp({ ...good, payload: { href } }), null, href);
  }
  assert.equal(parseFrameToApp({ ...good, payload: { href: `https://example.com/${"a".repeat(2100)}` } }), null);
});

// Site element inspector (plan 1): a selection may name one text element inside the section.
const ELEMENT = {
  key: "heading",
  kind: "text" as const,
  label: "Request a Provider Impact Analysis.",
  computed: { color: "#014036", fontFamily: "Garner Serif", fontSize: 48, fontWeight: 600, italic: false, underline: false, textAlign: "center" as const },
};

test("selected carries the chosen element and the section's text elements; select may name an element", () => {
  const selected = frameToApp(
    "selected",
    { route: "/", componentId: "cta", componentType: "CtaBand", fields: [], props: {}, element: ELEMENT, elements: [{ key: "heading", kind: "text", label: "Request…" }, { key: "body", kind: "text", label: "A free analysis" }] },
    ctx,
  );
  const parsed = parseFrameToApp(selected);
  assert.equal(parsed?.type, "selected");
  assert.deepEqual(parsed?.type === "selected" ? parsed.payload.element : null, ELEMENT);
  assert.equal(parseAppToFrame(appToFrame("select", { route: "/", componentId: "cta", elementKey: "heading" }, ctx))?.type, "select");
  assert.equal(parseAppToFrame(appToFrame("select", { route: "/", componentId: "cta", elementKey: null }, ctx))?.type, "select");
});

test("an element key or a computed colour that could break out of its place is dropped", () => {
  assert.equal(parseAppToFrame(appToFrame("select", { route: "/", componentId: "cta", elementKey: '"]{}' } as never, ctx)), null);
  const badColor = { ...ELEMENT, computed: { ...ELEMENT.computed, color: "red;}" } };
  assert.equal(parseFrameToApp(frameToApp("selected", { route: "/", componentId: "cta", componentType: "CtaBand", fields: [], props: {}, element: badColor } as never, ctx)), null);
});

// Plan 2: the selected element may carry where its rich text lives, the highlighted words, and where
// its link is written.
test("selected may carry the element's rich text source, its highlighted words and its link source", () => {
  const words = { start: 5, end: 13, count: 1, text: "Provider", computed: ELEMENT.computed };
  const element = { ...ELEMENT, rich: { prop: "heading" }, words, link: { source: { kind: "replacement" as const, find: "/demo", shared: true } } };
  const parsed = parseFrameToApp(frameToApp("selected", { route: "/", componentId: "cta", componentType: "CtaBand", fields: [], props: {}, element }, ctx));
  assert.deepEqual(parsed?.type === "selected" ? parsed.payload.element : null, element);
  for (const source of [{ kind: "prop", href: "linkHref", newTab: "linkNewTab" }, { kind: "slot", slot: "cta_href" }, { kind: "fixed", reason: "set by the agent's section" }]) {
    const ok = { ...ELEMENT, link: { source } };
    assert.equal(parseFrameToApp(frameToApp("selected", { route: "/", componentId: "cta", componentType: "CtaBand", fields: [], props: {}, element: ok } as never, ctx))?.type, "selected", JSON.stringify(source));
  }
});

test("highlighted words must be a real range, and a rich text source a real prop path", () => {
  const send = (element: object) => parseFrameToApp(frameToApp("selected", { route: "/", componentId: "cta", componentType: "CtaBand", fields: [], props: {}, element } as never, ctx));
  assert.equal(send({ ...ELEMENT, words: { start: 5, end: 5, count: 0, text: "", computed: ELEMENT.computed } }), null);
  assert.equal(send({ ...ELEMENT, rich: { prop: "a b" } }), null);
  assert.equal(send({ ...ELEMENT, link: { source: { kind: "prop", href: "x;y", newTab: "z" } } }), null);
});

test("a clone slot's name may have dashes or start with a digit (review finding 4), and a long captured address fits", () => {
  const element = { ...ELEMENT, rich: { prop: "slots.cta-label" }, link: { source: { kind: "replacement" as const, find: `/x?${"a".repeat(5000)}`, shared: false } } };
  const parsed = parseFrameToApp(frameToApp("selected", { route: "/", componentId: "cta", componentType: "ClonedSection", fields: [{ kind: "richtext", label: "2col", name: "slots.2col" }], props: {}, element }, ctx));
  assert.equal(parsed?.type, "selected");
  for (const bad of ["slots.a b", "slots.-x", "slots..x", "a.b;c"]) {
    assert.equal(parseFrameToApp(frameToApp("selected", { route: "/", componentId: "cta", componentType: "ClonedSection", fields: [], props: {}, element: { ...ELEMENT, rich: { prop: bad } } }, ctx)), null, bad);
  }
});

// Plan 3: a selected button carries its words, its look as drawn, and where its words are written.
test("a selected button carries its label, its computed box and its label source", () => {
  const element = {
    key: "button", kind: "button" as const, label: "Request the analysis", computed: ELEMENT.computed,
    labelElement: { key: "button.label", computed: ELEMENT.computed, rich: { prop: "buttonLabel" } },
    box: { fill: "#0F59B0", borderColor: "", borderWidth: 0, radius: [9999, 9999, 9999, 9999], paddingY: 12, paddingX: 22, width: 214 },
    labelSource: { kind: "prop" as const, prop: "buttonLabel" },
  };
  const parsed = parseFrameToApp(frameToApp("selected", { route: "/", componentId: "cta", componentType: "CtaBand", fields: [], props: {}, element, elements: [{ key: "button", kind: "button", label: "Request the analysis" }] }, ctx));
  assert.deepEqual(parsed?.type === "selected" ? parsed.payload.element : null, element);
  const bad = { ...element, box: { ...element.box, fill: "red;}" } };
  assert.equal(parseFrameToApp(frameToApp("selected", { route: "/", componentId: "cta", componentType: "CtaBand", fields: [], props: {}, element: bad } as never, ctx)), null);
  for (const source of [{ kind: "slot", slot: "cta-label" }, { kind: "replacement", find: "Book a demo" }, { kind: "fixed", reason: "ask the agent" }]) {
    assert.equal(parseFrameToApp(frameToApp("selected", { route: "/", componentId: "cta", componentType: "CtaBand", fields: [], props: {}, element: { ...element, labelSource: source } } as never, ctx))?.type, "selected");
  }
});
