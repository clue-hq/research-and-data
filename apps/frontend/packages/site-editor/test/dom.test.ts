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

test("findKeyedElement finds any keyed element by key (plan 4: boxes and images too), never outside its section", () => {
  assert.equal(findKeyedElement(section, "body")?.id, "b");
  assert.equal(findKeyedElement(section, "photo")?.id, "img");
  assert.equal(findKeyedElement(section, "card")?.id, "card");
  assert.equal(findKeyedElement(section, "nowhere"), null);
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
import { ComputedBoxSchema } from "@clue/site-kit/editor-protocol";

const buttonDom = new JSDOM(`
  <div data-puck-component="hero">
    <h2 id="t" data-clue-el="heading">Title</h2>
    <a id="brand" class="brand-btn" data-clue-el="button" style="background-color: rgb(15, 89, 176); border: 2px solid rgb(0, 0, 0); border-radius: 9999px; padding: 12px 22px"><span id="brandLabel" data-clue-el="button.label">Go</span></a>
    <div data-lumen-fragment="true">
    <a id="clone" data-clue-el="0.1" href="/demo" style="display: inline-block; background-color: rgb(15, 89, 176)"><svg></svg><span id="cloneLabel" data-clue-el="0.1.1">Book</span></a>
    <a id="plain" data-clue-el="0.2" href="/x">Plain link</a>
    <a id="card" data-clue-el="0.3" href="/c" style="display: block"><div><h3 id="cardTitle" data-clue-el="0.3.0.0">Card</h3></div></a>
    <button id="own" data-clue-el="0.4">Send</button>
    </div>
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
    fill: "#0F59B0", fillOpacity: 100, borderColor: "#000000", borderWidth: 2, radius: [9999, 9999, 9999, 9999], paddingY: 12, paddingX: 22, width: 120, height: 40,
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
  const menu = new JSDOM(`<nav data-lumen-fragment="true"><a id="nav" class="brand-navlink" data-clue-el="nav.0" href="/analysis" style="display: flex; padding: 8px">Analysis</a>
    <a id="outline" data-clue-el="0.1" href="/x" style="display: inline-flex; border: 1px solid rgb(0, 0, 0)">Outline</a></nav>`);
  const view = menu.window as unknown as Window;
  assert.equal(isButtonElement(menu.window.document.getElementById("nav")!, view), false);
  assert.equal(isButtonElement(menu.window.document.getElementById("outline")!, view), true, "a stroke is a box");
});

test("an empty keyed element (a copied button's overlay link) is not listed: it has nothing to show or style", () => {
  const webflow = new JSDOM(`<div data-puck-component="hero" data-lumen-fragment="true">
    <button data-clue-el="0.2"><div data-clue-el="0.2.0">Request a demo</div><a id="overlay" data-clue-el="0.2.1" href="/book"></a></button>
  </div>`);
  const view = webflow.window as unknown as Window;
  const scope = webflow.window.document.querySelector("[data-puck-component]")!;
  assert.deepEqual(inspectableElementsIn(scope, view).map(({ element }) => element.getAttribute("data-clue-el")), ["0.2.0"]);
});

test("outside a copied section only our own buttons are buttons: a boxed menu or card link stays a link (review 2)", () => {
  const ours = new JSDOM(`<header><a id="nav" class="brand-navlink" data-clue-el="nav.0" href="/a" style="background-color: rgb(1, 2, 3)">Analysis</a>
    <a id="proof" class="brand-link" data-clue-el="linkLabel" href="/b" style="border: 1px solid rgb(0, 0, 0)">Read</a>
    <a id="cta" class="brand-btn" data-clue-el="cta"><span data-clue-el="cta.label">Book</span></a></header>`);
  const view = ours.window as unknown as Window;
  const byId = (id: string) => ours.window.document.getElementById(id)!;
  assert.deepEqual(["nav", "proof", "cta"].map((id) => isButtonElement(byId(id), view)), [false, false, true]);
});

test("in a copied section a link holding an image or two texts is no button (review 5)", () => {
  const copied = new JSDOM(`<div data-lumen-fragment="true">
    <a id="card" data-clue-el="0.0" href="/c" style="background-color: rgb(1, 2, 3)"><img src="/x.png"><span data-clue-el="0.0.1">Title</span></a>
    <a id="two" data-clue-el="0.1" href="/d" style="background-color: rgb(1, 2, 3)"><span data-clue-el="0.1.0">Book</span><span data-clue-el="0.1.1">now</span></a>
  </div>`);
  const view = copied.window as unknown as Window;
  assert.equal(isButtonElement(copied.window.document.getElementById("card")!, view), false);
  assert.equal(isButtonElement(copied.window.document.getElementById("two")!, view), false);
});

test("a drawn box stays within what the message carries: huge and percentage corners, a half-clear fill (review 6, 7)", () => {
  const odd = new JSDOM(`<a id="b" class="brand-btn" data-clue-el="b" style="background-color: rgba(15, 89, 176, 0.5); border-radius: 50%; padding: 99999px 4px"></a>
    <a id="c" class="brand-btn" data-clue-el="c" style="border-radius: 9999999px"></a>`);
  const view = odd.window as unknown as Window;
  const b = odd.window.document.getElementById("b")!;
  const c = odd.window.document.getElementById("c")!;
  for (const element of [b, c]) (element as unknown as { getBoundingClientRect: () => unknown }).getBoundingClientRect = () => ({ left: 0, top: 0, right: 200, bottom: 40, width: 200, height: 40, x: 0, y: 0 });
  const box = computedBox(b, view, cssColorToHex);
  assert.deepEqual([box.fill, box.fillOpacity, box.radius, box.paddingY], ["#0F59B0", 50, [20, 20, 20, 20], 10000], "50% of the shorter side; padding held at the message's limit");
  assert.deepEqual(computedBox(c, view, cssColorToHex).radius, [100000, 100000, 100000, 100000]);
  assert.ok(ComputedBoxSchema.safeParse(computedBox(c, view, cssColorToHex)).success);
});

// Responsive brand type review 3: the frame reports how far the brand's headline and body sizes are
// scaled where the selected element is drawn now.
import { sizeScaleAt } from "../src/client/dom";
import { garner } from "../../site-kit/test/fixtures/garner";

test("the size scale is read from the brand's variables at the element; none on desktop or unmeasured kits", () => {
  const brand = garner(); // headline 87, title 56, body 16
  const roles = Object.fromEntries(["display", "headline", "title", "subtitle", "body", "body.small", "caption", "eyebrow", "label", "cta", "stat", "legal"].map((r) => [`type.${r}`, []]));
  const measuredKit = { ...brand, kit: { ...brand.kit, responsive_type: { roles } } };
  const view = (headline: string, body: string) => ({ getComputedStyle: () => ({ getPropertyValue: (name: string) => (name === "--brand-text-headline" ? headline : name === "--brand-text-body" ? body : "") }) }) as unknown as Window;
  const el = new JSDOM("<p></p>").window.document.querySelector("p")!;
  assert.deepEqual(sizeScaleAt(el, measuredKit, view("43.5px", "14.4px")), { headline: 0.5, body: 0.9, title: 56 });
  assert.equal(sizeScaleAt(el, measuredKit, view("87px", "16px")), null, "desktop");
  assert.equal(sizeScaleAt(el, brand, view("43.5px", "14.4px")), null, "a kit that did not measure its steps");
});

// Plan 4: boxes and images. A fake view gives each element the style a browser would draw, by id.
import { arrangeOf, computedContainer, containerName, isContainerElement, isImageElement, sectionBoxOf } from "../src/client/dom";

const BASE_STYLE: Record<string, string> = {
  display: "block", backgroundColor: "rgba(0, 0, 0, 0)", borderTopWidth: "0px", borderTopColor: "rgb(0, 0, 0)",
  borderTopLeftRadius: "0px", borderTopRightRadius: "0px", borderBottomRightRadius: "0px", borderBottomLeftRadius: "0px", borderRadius: "0px",
  paddingTop: "0px", paddingLeft: "0px", flexDirection: "row", justifyContent: "normal", alignItems: "normal", justifyItems: "normal",
  textAlign: "start", columnGap: "normal", rowGap: "normal", color: "rgb(0, 0, 0)", fontFamily: "Inter", fontSize: "16px", fontWeight: "400",
  fontStyle: "normal", textDecorationLine: "none", visibility: "visible",
};
const fakeView = (styles: Record<string, Record<string, string>>) => ({
  getComputedStyle: (element: Element) => {
    const style: Record<string, string> = { ...BASE_STYLE, ...(element.tagName === "SPAN" || element.tagName === "A" ? { display: "inline" } : {}), ...styles[element.id] };
    return { ...style, getPropertyValue: (name: string) => style[name.replace(/-([a-z])/g, (_, c: string) => c.toUpperCase())] ?? "" } as unknown as CSSStyleDeclaration;
  },
});
const stubBoxes = (scope: Element, boxes: Record<string, [number, number, number, number]>) => {
  for (const element of [scope, ...scope.querySelectorAll("*")]) {
    const [left, top, right, bottom] = boxes[element.id] ?? [0, 0, 0, 0];
    (element as unknown as { getBoundingClientRect: () => unknown }).getBoundingClientRect = () => ({ left, top, right, bottom, width: right - left, height: bottom - top, x: left, y: top });
  }
};

const boxDom = new JSDOM(`
  <div data-puck-component="stats" id="scope"><div class="clue-section">
    <section id="root" data-clue-el="root"><div id="inner" data-clue-el="root.inner">
      <dl id="grid" data-clue-el="stats">
        <div id="s0" data-clue-el="stats.0"><dt id="v0" data-clue-el="stats.0.value">7%</dt></div>
        <div id="s1" data-clue-el="stats.1"><dt id="v1" data-clue-el="stats.1.value">2x</dt></div>
      </dl>
      <div id="col" data-clue-el="column"><h2 id="h" data-clue-el="heading">H</h2><p id="b" data-clue-el="body">B</p></div>
      <ul id="list" data-clue-el="list"><li id="li0" data-clue-el="list.0"><p id="li0t" data-clue-el="list.0.t">One</p></li><li id="li1" data-clue-el="list.1"><p id="li1t" data-clue-el="list.1.t">Two</p></li></ul>
      <div id="wrap" data-clue-el="0.1"><div id="card" data-clue-el="0.1.0"><p id="ct" data-clue-el="0.1.0.0">Card</p></div></div>
      <span id="inl" data-clue-el="inl"><svg id="icon" data-clue-el="inl.0"></svg></span>
      <img id="photo" data-clue-el="image" src="/x.png">
    </div></section>
  </div></div>`);
const bx = (id: string) => boxDom.window.document.getElementById(id)!;
const boxScope = bx("scope");
stubBoxes(boxScope, {
  scope: [0, 0, 1000, 800], root: [0, 0, 1000, 800], inner: [0, 0, 1000, 800],
  grid: [0, 0, 1000, 200], s0: [0, 0, 480, 200], v0: [10, 10, 100, 40], s1: [520, 0, 1000, 200], v1: [530, 10, 620, 40],
  col: [0, 220, 1000, 320], h: [0, 220, 1000, 260], b: [0, 270, 1000, 300],
  list: [0, 330, 1000, 400], li0: [0, 330, 1000, 360], li0t: [0, 330, 200, 360], li1: [0, 370, 1000, 400], li1t: [0, 370, 200, 400],
  wrap: [0, 420, 500, 600], card: [0, 420, 500, 600], ct: [10, 430, 200, 460],
  inl: [600, 420, 620, 440], icon: [600, 420, 620, 440], photo: [600, 450, 800, 600],
});
const boxStyles: Record<string, Record<string, string>> = {
  grid: { display: "grid", columnGap: "24px", justifyItems: "center" },
  s0: { backgroundColor: "rgb(255, 255, 255)", borderTopLeftRadius: "8px" },
  col: { display: "flex", flexDirection: "column", alignItems: "center" },
  card: { backgroundColor: "rgb(255, 255, 255)", borderTopLeftRadius: "12px", borderTopRightRadius: "12px", borderBottomRightRadius: "12px", borderBottomLeftRadius: "12px", paddingTop: "24px", paddingLeft: "32px" },
  list: { display: "block" },
};
const boxView = fakeView(boxStyles) as unknown as Window;

test("boxes and images: a grid, a stack, cards, a list and its items are containers with their names and layouts", () => {
  const grid = computedContainer(bx("grid"), boxView, cssColorToHex);
  assert.equal(grid.layout, "grid");
  assert.equal(grid.gap, 24);
  assert.equal(grid.contentAlign, "center");
  assert.equal(grid.name, "Grid");
  const col = computedContainer(bx("col"), boxView, cssColorToHex);
  assert.deepEqual([col.layout, col.contentAlign, col.name], ["stack", "center", "Column"]);
  assert.equal(containerName(bx("s0"), boxView), "Card", "a stat is a card");
  assert.equal(containerName(bx("card"), boxView), "Card", "a filled box with corners");
  assert.equal(containerName(bx("list"), boxView), "List");
  assert.equal(containerName(bx("li0"), boxView), "List item");
  const card = computedContainer(bx("card"), boxView, cssColorToHex);
  assert.deepEqual([card.fill, card.paddingY, card.paddingX, card.radius[0], card.layout], ["#FFFFFF", 24, 32, 12, "text"]);
  assert.equal(isContainerElement(bx("inl"), boxView), false, "an inline span is no box");
  assert.equal(isContainerElement(bx("h"), boxView), false, "a heading is text");
  assert.equal(isImageElement(bx("photo")), true);
  assert.equal(isImageElement(bx("icon")), true);
});

test("a click between two cards selects their grid; on a card the card; on its words the words; on blank section space nothing (the section)", () => {
  assert.equal(elementKeyAt(boxScope, boxScope, { x: 500, y: 100 }, boxView), "stats");
  assert.equal(elementKeyAt(boxScope, boxScope, { x: 300, y: 150 }, boxView), "stats.0");
  assert.equal(elementKeyAt(boxScope, boxScope, { x: 50, y: 25 }, boxView), "stats.0.value");
  assert.equal(elementKeyAt(boxScope, boxScope, { x: 400, y: 550 }, boxView), "0.1.0", "the card, not its pass-through wrapper");
  assert.equal(elementKeyAt(boxScope, boxScope, { x: 700, y: 500 }, boxView), "image");
  assert.equal(elementKeyAt(boxScope, boxScope, { x: 900, y: 700 }, boxView), null, "the section's own box is never a click target");
  assert.equal(elementKeyAt(boxScope, bx("ct"), { x: -1, y: -1 }, boxView), "0.1.0.0", "a direct hit picks the innermost element");
});

test("a pass-through wrapper is neither listed nor clickable; a wrapper with its own fill is", () => {
  const listed = (view: Window) => inspectableElementsIn(boxScope, view).map(({ element }) => element.id);
  assert.ok(!listed(boxView).includes("wrap"));
  assert.ok(listed(boxView).includes("card"));
  const filled = fakeView({ ...boxStyles, wrap: { backgroundColor: "rgb(1, 2, 3)" } }) as unknown as Window;
  assert.ok(listed(filled).includes("wrap"));
});

test("Layers' tree: each element's parent is its nearest listed ancestor; the section's own box is left out", () => {
  const tree = Object.fromEntries(inspectableElementsIn(boxScope, boxView).map(({ element, kind, parent }) => [element.id, `${kind}<${parent ?? "-"}`]));
  assert.deepEqual(tree, {
    grid: "container<-", s0: "container<stats", v0: "text<stats.0", s1: "container<stats", v1: "text<stats.1",
    col: "container<-", h: "text<column", b: "text<column",
    list: "container<-", li0: "container<list", li0t: "text<list.0", li1: "container<list", li1t: "text<list.1",
    card: "container<-", ct: "text<0.1.0", icon: "image<-", photo: "image<-",
  });
});

const headerDom = new JSDOM(`
  <div class="brand-root"><header id="hroot" data-clue-section="shell-header" data-clue-el="root"><div id="hinner" data-clue-el="root.inner">
    <div id="brand" data-clue-el="brand"><img id="logo" data-clue-el="logo" src="/l.png"><span id="prep" data-clue-el="prepared"><span id="name" data-clue-el="preparedFor">Carmel</span></span></div>
    <div id="actions" data-clue-el="actions"><nav id="nav" data-clue-el="nav"><a id="n0" data-clue-el="nav.0" href="/a">A</a></nav><span id="area" data-clue-el="ctaArea"><a id="cta" class="brand-btn" data-clue-el="cta"><span id="ctal" data-clue-el="cta.label">Go</span></a></span></div>
  </div></header></div>`);
const hx = (id: string) => headerDom.window.document.getElementById(id)!;
stubBoxes(hx("hroot"), { hroot: [0, 0, 1000, 60], hinner: [0, 0, 1000, 60], brand: [0, 0, 400, 60], prep: [100, 10, 300, 50], name: [180, 10, 300, 50], actions: [600, 0, 1000, 60], nav: [600, 10, 800, 50], n0: [600, 10, 640, 50], area: [820, 10, 1000, 50], cta: [820, 10, 1000, 50], ctal: [840, 20, 980, 40] });
const headerView = fakeView({ brand: { display: "flex" }, actions: { display: "flex" }, nav: { display: "flex" }, area: { display: "inline-flex" }, prep: { display: "inline" } }) as unknown as Window;

test("arrangeOf: a stat among stats; a heading among its keyed neighbours; the header's button through its area; none for a section's box", () => {
  assert.deepEqual(arrangeOf(bx("s1"), boxScope), { item: "stats.1", parent: "stats", siblings: ["stats.0", "stats.1"] });
  assert.deepEqual(arrangeOf(bx("h"), boxScope), { item: "heading", parent: "column", siblings: ["heading", "body"] });
  assert.deepEqual(arrangeOf(hx("cta"), hx("hroot")), { item: "ctaArea", parent: "actions", siblings: ["nav", "ctaArea"] });
  assert.equal(arrangeOf(bx("root"), boxScope), null);
  assert.equal(arrangeOf(hx("n0"), hx("hroot")), null, "a lone menu link has no neighbour");
});

test("the section's box: ours and the shell's are root and root.inner; a copied section's is its one top element", () => {
  const ours = sectionBoxOf(boxScope);
  assert.deepEqual([ours?.outer.id, ours?.inner.id], ["root", "inner"]);
  const shell = sectionBoxOf(hx("hroot"));
  assert.deepEqual([shell?.outer.id, shell?.inner.id], ["hroot", "hinner"]);
  const copied = new JSDOM(`<div id="c"><div class="clue-section"><div data-lumen-fragment="true"><section id="top" data-clue-el="0"><p data-clue-el="0.0">x</p></section></div></div></div>`).window.document;
  const box = sectionBoxOf(copied.getElementById("c")!);
  assert.deepEqual([box?.outer.id, box?.inner.id], ["top", "top"]);
  const two = new JSDOM(`<div id="c"><div data-lumen-fragment="true"><p data-clue-el="0">a</p><p data-clue-el="1">b</p></div></div>`).window.document;
  assert.equal(sectionBoxOf(two.getElementById("c")!), null, "two top elements: no one box");
});

test("a hidden header part is listed hidden even with no box; an inline span is not a container", () => {
  const found = inspectableElementsIn(hx("hroot"), headerView, new Set(["logo"]));
  const logo = found.find(({ element }) => element.id === "logo");
  assert.deepEqual(logo && { kind: logo.kind, hidden: logo.hidden, parent: logo.parent }, { kind: "image", hidden: true, parent: "brand" });
  assert.ok(!found.some(({ element }) => element.id === "prep"), "the inline Prepared-for line is part of its group, not a box");
  assert.ok(!found.some(({ element }) => element.id === "area"), "the button's area is a pass-through wrapper (moving the button moves it)");
  assert.ok(found.some(({ element, kind }) => element.id === "cta" && kind === "button"));
});

// End-of-plan review fixes (plan 4).
const realDom = new JSDOM(`
  <div data-puck-component="hero" id="rscope"><div class="clue-section"><div data-lumen-fragment="true">
    <ls-h id="lsh" data-clue-el="0"><ls-b id="lsb" data-clue-el="0.0"><section id="sec" data-clue-el="0.0.0">
      <div id="bgov" data-clue-el="0.0.0.0"></div>
      <div id="rcard" data-clue-el="0.0.0.1"><h3 id="rct" data-clue-el="0.0.0.1.0">Card</h3><a id="overlay" data-clue-el="0.0.0.1.1" href="/x"></a></div>
      <div id="agentcard" class="brand-card" data-clue-el="cards.0"><h3>Unnamed title</h3><p>Unnamed words</p></div>
      <div id="hug" data-clue-el="0.0.0.3"><a id="h0" data-clue-el="0.0.0.3.0" href="/a">A</a><a id="h1" data-clue-el="0.0.0.3.1" href="/b">B</a></div>
      <div id="roomy" data-clue-el="0.0.0.4"><a id="r0" data-clue-el="0.0.0.4.0" href="/a">A</a></div>
    </section></ls-b></ls-h>
  </div></div></div>`);
const rx = (id: string) => realDom.window.document.getElementById(id)!;
const realScope = rx("rscope");
stubBoxes(realScope, {
  rscope: [0, 0, 1000, 600], sec: [0, 0, 1000, 600], bgov: [0, 0, 1000, 600],
  rcard: [40, 40, 440, 240], rct: [64, 64, 300, 100], overlay: [40, 40, 440, 240],
  agentcard: [500, 40, 900, 240],
  hug: [40, 300, 200, 340], h0: [40, 300, 110, 340], h1: [130, 300, 200, 340],
  roomy: [40, 400, 900, 440], r0: [40, 400, 110, 440],
});
const realView = fakeView({
  lsh: { display: "contents" }, lsb: { display: "contents" }, bgov: { position: "absolute" },
  rcard: { backgroundColor: "rgb(255, 255, 255)" }, overlay: { display: "block", position: "absolute" },
  hug: { display: "flex", columnGap: "20px" }, roomy: { display: "flex" }, h0: { display: "block" }, h1: { display: "block" }, r0: { display: "block" },
}) as unknown as Window;

test("review C1: a copied section's box is its first element that draws one, under display:contents wrappers", () => {
  const box = sectionBoxOf(realScope, realView);
  assert.deepEqual([box?.outer.id, box?.inner.id], ["sec", "sec"]);
  const listed = inspectableElementsIn(realScope, realView).map(({ element }) => element.id);
  assert.ok(!listed.includes("sec") && !listed.includes("lsh") && !listed.includes("lsb"), listed.join(","));
  assert.equal(elementKeyAt(realScope, realScope, { x: 950, y: 580 }, realView), null, "blank section space is the section");
});

test("review I3: an empty overlay or decoration with no fill or stroke is no box and never takes a click", () => {
  const listed = inspectableElementsIn(realScope, realView).map(({ element }) => element.id);
  assert.ok(!listed.includes("bgov") && !listed.includes("overlay"), listed.join(","));
  assert.equal(elementKeyAt(realScope, realScope, { x: 420, y: 220 }, realView), "0.0.0.1", "the card's padding selects the card");
  const filled = fakeView({ bgov: { backgroundColor: "rgb(0, 0, 0)" }, lsh: { display: "contents" }, lsb: { display: "contents" } }) as unknown as Window;
  assert.ok(inspectableElementsIn(realScope, filled).some(({ element }) => element.id === "bgov"), "a visible decoration is a box");
});

test("review I4: a named box holding unnamed blocks (an agent's kit.Card) is a box, not text", () => {
  const card = inspectableElementsIn(realScope, realView).find(({ element }) => element.id === "agentcard");
  assert.equal(card?.kind, "container");
  assert.equal(isContainerElement(rx("agentcard"), realView), true);
});

test("review I5: a box as wide as its contents has no room to line them up; one with room does", () => {
  assert.equal(computedContainer(rx("hug"), realView, cssColorToHex).alignRoom, false);
  assert.equal(computedContainer(rx("roomy"), realView, cssColorToHex).alignRoom, true);
});

test("review I4 follow-up: a heading holding Puck's in-place editor (its own blocks) is still text", () => {
  const editing = new JSDOM(`<div id="s" data-puck-component="p"><h2 id="h" data-clue-el="heading"><div data-puck-overlay-portal="true"><div class="ProseMirror" contenteditable="true"><p>Words</p></div></div></h2><div id="q" data-clue-el="quote"><div contenteditable="true"><p>Agent words</p></div></div></div>`).window.document;
  const scope = editing.getElementById("s")!;
  stubBoxes(scope, { s: [0, 0, 500, 300], h: [0, 0, 500, 60], q: [0, 100, 500, 160] });
  const kinds = Object.fromEntries(inspectableElementsIn(scope, fakeView({}) as unknown as Window).map(({ element, kind }) => [element.id, kind]));
  assert.deepEqual(kinds, { h: "text", q: "text" });
});

// Live check 2026-10-18: on a real copied hero a full-width column with its own padding covers the
// section, so blank space in it meant that column; a box covering nearly all of the section's box is
// part of the section for a click (it stays in Layers, selectable there).
test("a box covering nearly all of the section is no click target; blank space in it selects the section", () => {
  const doc = new JSDOM(`
    <div id="hs" data-puck-component="hero"><div class="clue-section"><div data-lumen-fragment="true">
      <section id="hsec" data-clue-el="0">
        <div id="cover" data-clue-el="0.0"><h1 id="ht" data-clue-el="0.0.0">Title</h1>
          <div id="narrow" data-clue-el="0.0.1"><div id="hcard" data-clue-el="0.0.1.0"><p id="hp" data-clue-el="0.0.1.0.0">Card</p></div><div id="hcard2" data-clue-el="0.0.1.1"><p data-clue-el="0.0.1.1.0">Two</p></div></div>
        </div>
      </section>
    </div></div></div>`).window.document;
  const scope = doc.getElementById("hs")!;
  stubBoxes(scope, {
    hs: [0, 0, 1000, 600], hsec: [0, 0, 1000, 600], cover: [0, 10, 1000, 590], ht: [100, 60, 900, 120],
    narrow: [200, 200, 800, 500], hcard: [200, 200, 480, 500], hp: [220, 220, 400, 260], hcard2: [520, 200, 800, 500],
  });
  const view = fakeView({ cover: { paddingTop: "48px", paddingLeft: "48px" }, narrow: { display: "flex" }, hcard: { backgroundColor: "rgb(255, 255, 255)" } }) as unknown as Window;
  assert.equal(elementKeyAt(scope, scope, { x: 950, y: 560 }, view), null, "blank space in the covering column is the section");
  assert.equal(elementKeyAt(scope, scope, { x: 500, y: 350 }, view), "0.0.1", "a narrower box is still a target");
  assert.equal(elementKeyAt(scope, scope, { x: 300, y: 450 }, view), "0.0.1.0");
  assert.ok(inspectableElementsIn(scope, view).some(({ element }) => element.id === "cover"), "still listed in Layers");
});
