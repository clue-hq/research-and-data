import assert from "node:assert/strict";
import { test } from "node:test";
import { JSDOM } from "jsdom";
import { clickIntent, rangeAt, rectOf, selectionOffsets, wordCount } from "../src/client/dom";

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

// Plan 2: highlighted words as character offsets inside the selected text element, counted as the
// browser's textContent counts them (a line break is no character), and back.
test("a highlighted range is its offsets inside the element, across marks and line breaks", () => {
  const page = new JSDOM('<h2 id="h">Top <strong>providers</strong><br>win <a href="/x">big</a><br class="ProseMirror-trailingBreak"></h2>');
  const h = page.window.document.getElementById("h")!;
  const range = page.window.document.createRange();
  const strong = h.querySelector("strong")!.firstChild!;
  const link = h.querySelector("a")!.firstChild!;
  range.setStart(strong, 3);
  range.setEnd(link, 2);
  assert.deepEqual(selectionOffsets(h, range), { start: 7, end: 19, text: "viderswin bi" });
  const back = rangeAt(h, 7, 19)!;
  assert.equal(back.toString(), "viderswin bi");
  const outside = page.window.document.createRange();
  outside.selectNodeContents(page.window.document.body);
  assert.equal(selectionOffsets(h, outside), null, "a range not inside the element");
  assert.equal(rangeAt(h, 3, 99), null, "offsets past the text");
});

test("words are counted as a reader counts them", () => {
  assert.equal(wordCount(" Top  providers win "), 3);
  assert.equal(wordCount("provi"), 1);
  assert.equal(wordCount("   "), 0);
});

// Plan 3: buttons. A keyed link or button with inline-only content that the browser draws as a box.
import { buttonAround, buttonLabelOf, computedBox, inspectableElementsIn, isButtonElement } from "../src/client/dom";

const buttonDom = new JSDOM(`
  <div data-puck-component="hero">
    <h2 id="t" data-clue-el="heading">Title</h2>
    <a id="brand" class="brand-btn" data-clue-el="button" style="background-color: rgb(15, 89, 176); border: 2px solid rgb(0, 0, 0); border-radius: 9999px; padding: 12px 22px"><span id="brandLabel" data-clue-el="button.label">Go</span></a>
    <a id="clone" data-clue-el="0.1" href="/demo" style="display: inline-block; background-color: rgb(15, 89, 176)"><svg></svg><span id="cloneLabel" data-clue-el="0.1.1">Book</span></a>
    <a id="plain" data-clue-el="0.2" href="/x">Plain link</a>
    <a id="card" data-clue-el="0.3" href="/c" style="display: block"><div><h3 id="cardTitle" data-clue-el="0.3.0.0">Card</h3></div></a>
    <button id="own" data-clue-el="0.4">Send</button>
  </div>`);
const bwin = buttonDom.window as unknown as Window;
const bel = (id: string) => buttonDom.window.document.getElementById(id)!;
const hero = buttonDom.window.document.querySelector("[data-puck-component]")!;
const buttonBoxes: Record<string, { left: number; top: number; right: number; bottom: number }> = {
  t: { left: 0, top: 0, right: 400, bottom: 40 },
  brand: { left: 0, top: 50, right: 120, bottom: 90 },
  brandLabel: { left: 20, top: 60, right: 100, bottom: 80 },
  clone: { left: 140, top: 50, right: 260, bottom: 90 },
  cloneLabel: { left: 160, top: 60, right: 240, bottom: 80 },
};
for (const element of hero.querySelectorAll("*")) {
  const box = buttonBoxes[element.id] ?? { left: -1, top: -1, right: -1, bottom: -1 };
  (element as unknown as { getBoundingClientRect: () => unknown }).getBoundingClientRect = () => ({ ...box, width: box.right - box.left, height: box.bottom - box.top, x: box.left, y: box.top });
}

test("a button is a keyed link or button with inline-only content drawn as a box; a text link and a card link are not", () => {
  assert.equal(isButtonElement(bel("brand"), bwin), true);
  assert.equal(isButtonElement(bel("clone"), bwin), true, "a link with a fill");
  assert.equal(isButtonElement(bel("own"), bwin), true, "a <button>");
  assert.equal(isButtonElement(bel("plain"), bwin), false, "an inline text link");
  assert.equal(isButtonElement(bel("card"), bwin), false, "a link holding a block is a card");
});

test("Layers' elements: text and buttons; a button's words are part of it; a card's heading is text", () => {
  assert.deepEqual(
    inspectableElementsIn(hero, bwin).map(({ element, kind }) => `${element.id}:${kind}`),
    ["t:text", "brand:button", "clone:button", "plain:text", "cardTitle:text", "own:button"],
  );
});

test("a click on a button's words selects the button; its label is its words' element", () => {
  const { elementKeyAt: keyAt } = { elementKeyAt };
  assert.equal(keyAt(hero, bel("brandLabel"), { x: 30, y: 70 }, bwin), "button");
  assert.equal(keyAt(hero, hero, { x: 200, y: 70 }, bwin), "0.1");
  assert.equal(buttonAround(bel("cloneLabel").firstChild, bwin)?.id, "clone");
  assert.equal(buttonLabelOf(bel("brand"))?.id, "brandLabel");
  assert.equal(buttonLabelOf(bel("clone"))?.id, "cloneLabel");
  assert.equal(buttonLabelOf(bel("own"))?.id, "own", "words of its own");
});

test("a button's box as drawn", () => {
  assert.deepEqual(computedBox(bel("brand"), bwin, cssColorToHex), {
    fill: "#0F59B0", borderColor: "#000000", borderWidth: 2, radius: [9999, 9999, 9999, 9999], paddingY: 12, paddingX: 22, width: 120,
  });
});

test("a button whose words are being edited in place is still a button (Puck's editor sits inside them)", () => {
  const editing = new JSDOM(`<div data-puck-component="what">
    <a id="b" class="brand-btn" data-clue-el="button"><span id="l" data-clue-el="button.label"><div data-puck-overlay-portal="true"><div class="rich-text"><div contenteditable="true"><p id="p">Request</p></div></div></div></span></a>
  </div>`);
  const view = editing.window as unknown as Window;
  const button = editing.window.document.getElementById("b")!;
  assert.equal(isButtonElement(button, view), true);
  assert.equal(buttonAround(editing.window.document.getElementById("p"), view)?.id, "b");
  assert.equal(buttonLabelOf(button)?.id, "l");
});

test("a link laid out as a block but with no fill and no stroke reads as a link, not a button (a menu link)", () => {
  const menu = new JSDOM(`<nav><a id="nav" class="brand-navlink" data-clue-el="nav.0" href="/analysis" style="display: flex; padding: 8px">Analysis</a>
    <a id="outline" data-clue-el="0.1" href="/x" style="display: inline-flex; border: 1px solid rgb(0, 0, 0)">Outline</a></nav>`);
  const view = menu.window as unknown as Window;
  assert.equal(isButtonElement(menu.window.document.getElementById("nav")!, view), false);
  assert.equal(isButtonElement(menu.window.document.getElementById("outline")!, view), true, "a stroke is a box");
});

test("an empty keyed element (a copied button's overlay link) is not listed: it has nothing to show or style", () => {
  const webflow = new JSDOM(`<div data-puck-component="hero">
    <button data-clue-el="0.2"><div data-clue-el="0.2.0">Request a demo</div><a id="overlay" data-clue-el="0.2.1" href="/book"></a></button>
  </div>`);
  const view = webflow.window as unknown as Window;
  const scope = webflow.window.document.querySelector("[data-puck-component]")!;
  assert.deepEqual(inspectableElementsIn(scope, view).map(({ element }) => element.getAttribute("data-clue-el")), ["0.2.0"]);
});
