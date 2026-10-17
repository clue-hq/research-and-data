import assert from "node:assert/strict";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import { clickIntent, rectOf } from "../src/client/dom";

const dom = new JSDOM(`
  <div class="brand-root">
    <header><a id="nav" href="/analysis">Analysis</a></header>
    <div data-puck-component="proof"><h2 id="heading">Stats</h2><a id="cta" href="https://garnerhealth.com">Go</a></div>
    <a id="anchor" href="#top">Top</a>
    <footer><span id="legal">©</span></footer>
  </div>`);
const byId = (id: string) => dom.window.document.getElementById(id);

function summary(intent: ReturnType<typeof clickIntent>) {
  const { action, preventDefault } = intent;
  if (action.kind === "navigate") return { href: action.href, kind: action.kind, preventDefault };
  if (action.kind === "shell") return { kind: action.kind, part: action.part, preventDefault };
  if (action.kind === "component") return { componentId: action.componentId, kind: action.kind, preventDefault };
  return { kind: action.kind, preventDefault };
}

test("preview mode follows links and leaves in-page anchors to the browser", () => {
  assert.deepEqual(summary(clickIntent(byId("nav"), "preview")), { href: "/analysis", kind: "navigate", preventDefault: true });
  assert.deepEqual(summary(clickIntent(byId("cta"), "preview")), {
    href: "https://garnerhealth.com",
    kind: "navigate",
    preventDefault: true,
  });
  assert.deepEqual(summary(clickIntent(byId("anchor"), "preview")), { kind: "none", preventDefault: false });
  assert.deepEqual(summary(clickIntent(byId("heading"), "preview")), { kind: "none", preventDefault: false });
});

test("edit mode selects the header, the footer or a section, and never follows a link", () => {
  assert.deepEqual(summary(clickIntent(byId("nav"), "edit")), { kind: "shell", part: "header", preventDefault: true });
  assert.deepEqual(summary(clickIntent(byId("legal"), "edit")), { kind: "shell", part: "footer", preventDefault: false });
  assert.deepEqual(summary(clickIntent(byId("heading"), "edit")), { componentId: "proof", kind: "component", preventDefault: false });
  assert.deepEqual(summary(clickIntent(byId("cta"), "edit")), { componentId: "proof", kind: "component", preventDefault: true });
  assert.deepEqual(summary(clickIntent(byId("heading")?.firstChild ?? null, "edit")), {
    componentId: "proof",
    kind: "component",
    preventDefault: false,
  });
});

test("geometry is the element's box in viewport and document coordinates", () => {
  const element = { getBoundingClientRect: () => ({ bottom: 60, height: 50, left: 5, right: 105, top: 10, width: 100, x: 5, y: 10 }) };
  const geometry = rectOf(element as unknown as Element, { x: 0, y: 400 });
  assert.equal(geometry.viewport.top, 10);
  assert.equal(geometry.document.top, 410);
  assert.equal(geometry.document.y, 410);
  assert.equal(geometry.document.left, 5);
});

// Site element inspector (plan 1): Puck turns pointer events off inside every section, so a click
// lands on the section itself; the text under the pointer is found by its box.
import { computedTypography, elementKeyAt, findKeyedElement, keyedElementsIn, cssColorToHex } from "../src/client/dom";

const sectionDom = new JSDOM(`
  <div data-puck-component="cta">
    <div class="clue-section">
      <h2 id="h" data-clue-el="heading">Request <b>now</b></h2>
      <p id="b" data-clue-el="body">A free analysis</p>
      <div id="card" data-clue-el="card"><span id="inner" data-clue-el="card.title">Inner</span></div>
      <img id="img" data-clue-el="photo" src="/x.png">
      <a id="btn" class="brand-btn" data-clue-el="button">Go</a>
      <p id="bad" data-clue-el='"]{}body{'>Hostile</p>
      <p id="dup" data-clue-el="body">Second body</p>
    </div>
  </div>`);
const sectionEl = (id: string) => sectionDom.window.document.getElementById(id)!;
const section = sectionDom.window.document.querySelector("[data-puck-component]")!;
const boxes: Record<string, { left: number; top: number; right: number; bottom: number }> = {
  h: { left: 0, top: 0, right: 400, bottom: 60 },
  b: { left: 0, top: 70, right: 400, bottom: 100 },
  card: { left: 0, top: 110, right: 400, bottom: 200 },
  inner: { left: 10, top: 120, right: 200, bottom: 150 },
  bad: { left: 0, top: 210, right: 400, bottom: 240 },
};
for (const element of section.querySelectorAll("*")) {
  const box = boxes[element.id] ?? { left: -1, top: -1, right: -1, bottom: -1 };
  (element as unknown as { getBoundingClientRect: () => unknown }).getBoundingClientRect = () => ({ ...box, width: box.right - box.left, height: box.bottom - box.top, x: box.left, y: box.top });
}

test("the section's text elements: keyed, valid keys, no images, buttons or containers of other keyed text, first of a repeated key", () => {
  assert.deepEqual(keyedElementsIn(section).map((element) => element.id), ["h", "b", "inner"]);
});

test("the key under the pointer: the innermost text box that contains it; none outside every box", () => {
  assert.equal(elementKeyAt(section, section, { x: 50, y: 30 }), "heading");
  assert.equal(elementKeyAt(section, section, { x: 50, y: 130 }), "card.title");
  assert.equal(elementKeyAt(section, section, { x: 300, y: 180 }), null, "the card is not text");
  assert.equal(elementKeyAt(section, section, { x: 50, y: 225 }), null, "a hostile key is never selectable");
  assert.equal(elementKeyAt(section, section, { x: 900, y: 900 }), null);
});

test("a click whose target is inside a text element (an in-place field) needs no hit test", () => {
  assert.equal(elementKeyAt(section, sectionEl("h").querySelector("b"), { x: -50, y: -50 }), "heading");
});

test("findKeyedElement finds a text element by key, never outside its section", () => {
  assert.equal(findKeyedElement(section, "body")?.id, "b");
  assert.equal(findKeyedElement(section, "photo"), null);
  assert.equal(findKeyedElement(section, '"]{}body{'), null);
});

test("computed colours become #RRGGBB; typography maps start/end alignment and weights", () => {
  assert.equal(cssColorToHex("rgb(15, 89, 176)"), "#0F59B0");
  assert.equal(cssColorToHex("rgba(1, 64, 54, 0.5)"), "#014036");
  assert.equal(cssColorToHex("#abc"), "#AABBCC");
  assert.equal(cssColorToHex("oklch(0.5 0.1 200)"), null);
  const style = { color: "rgb(1, 64, 54)", fontFamily: '"Garner Serif", Georgia, serif', fontSize: "48px", fontWeight: "600", fontStyle: "italic", textDecorationLine: "underline", textAlign: "start" };
  const typography = computedTypography(sectionEl("h"), { getComputedStyle: () => style as unknown as CSSStyleDeclaration }, cssColorToHex);
  assert.deepEqual(typography, { color: "#014036", fontFamily: "Garner Serif", fontSize: 48, fontWeight: 600, italic: true, underline: true, textAlign: "left" });
});
