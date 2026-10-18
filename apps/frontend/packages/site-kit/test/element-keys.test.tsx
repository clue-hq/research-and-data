// Site element inspector, plan 1 Task 3: every text element a marketer can style carries a stable
// key (data-clue-el), the same in the editor and on the published page.
import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { parse } from "node-html-parser";
import { renderToStaticMarkup } from "react-dom/server";
import type { ReactNode } from "react";
import { makeKit } from "../src/agent-kit";
import type { Clone } from "../src/clone";
import { fillClone } from "../src/clone";
import { ELEMENT_KEY_ATTR } from "../src/edits";
import { makeSections } from "../src/sections";
import { SiteFooter, SiteHeader } from "../src/shell";
import { garner } from "./fixtures/garner";

const brand = garner();
const href = (value: string) => value;
const sections = makeSections(brand, href);
const keys = (html: string) => [...html.matchAll(/data-clue-el="([^"]*)"/g)].map((m) => m[1]);
const draw = (node: ReactNode) => renderToStaticMarkup(<>{node}</>);

test("the key attribute is the one the inspector reads", () => {
  assert.equal(ELEMENT_KEY_ATTR, "data-clue-el");
});

test("brand sections name each text element by the prop it draws", () => {
  assert.deepEqual(
    keys(draw(sections.StatsBand.render({ id: "s", surface: "page", align: "left", eyebrow: "E", heading: "H", intro: "I", stats: [{ value: "7%", label: "less" }, { value: "2x", label: "more" }], source: "S" } as never))),
    ["root", "root.inner", "lead", "eyebrow", "heading", "intro", "stats", "stats.0", "stats.0.value", "stats.0.label", "stats.1", "stats.1.value", "stats.1.label", "source"],
  );
  assert.deepEqual(
    keys(draw(sections.FeatureSplit.render({ id: "f", surface: "page", eyebrow: "E", heading: "H", headingRole: "title", body: "B", image: "", imageSide: "left", buttonLabel: "Go", buttonHref: "/", buttonLook: "" } as never))),
    ["root", "root.inner", "row", "column", "eyebrow", "heading", "body", "button", "button.label"],
  );
  assert.deepEqual(
    keys(draw(sections.FeatureSplit.render({ id: "f", surface: "page", eyebrow: "", heading: "H", headingRole: "title", body: "B", image: "/brands/x.png", imageSide: "left", buttonLabel: "", buttonHref: "/", buttonLook: "" } as never))),
    ["root", "root.inner", "row", "image", "column", "heading", "body"],
  );
  assert.deepEqual(
    keys(draw(sections.ProofCard.render({ id: "p", surface: "card", kicker: "K", metric: "13%", metricLabel: "L", heading: "H", body: "B", source: "S", linkLabel: "Read", linkHref: "/x" } as never))),
    ["root", "root.inner", "card", "figure", "kicker", "metric", "metricLabel", "story", "heading", "body", "source", "linkLabel"],
  );
  assert.deepEqual(
    keys(draw(sections.CtaBand.render({ id: "c", surface: "brand", heading: "H", body: "B", buttonLabel: "Go", buttonHref: "/", buttonLook: "" } as never))),
    ["root", "root.inner", "column", "heading", "body", "button", "button.label"],
  );
});

test("an empty optional text draws no element and so no key", () => {
  assert.deepEqual(
    keys(draw(sections.CtaBand.render({ id: "c", surface: "brand", heading: "H", body: "", buttonLabel: "Go", buttonHref: "/", buttonLook: "" } as never))),
    ["root", "root.inner", "column", "heading", "button", "button.label"],
  );
});

const header = { preparedFor: "Carmel Clay Schools", accountLogo: "/brands/carmel.png", ctaLabel: "Go", ctaHref: "/", nav: [{ label: "Analysis", href: "/analysis" }] };
const footer = { legal: "© 2026", privacyHref: "/privacy", termsHref: "/terms" };

test("the header and footer key every part (plan 4)", () => {
  assert.deepEqual(keys(draw(<SiteHeader brand={brand} header={header} href={href} />)), [
    "root", "root.inner", "brand", "logo", "divider", "accountLogo", "prepared", "preparedFor", "actions", "nav", "nav.0", "ctaArea", "cta", "cta.label",
  ]);
  assert.deepEqual(keys(draw(<SiteFooter brand={brand} footer={footer} href={href} />)), ["root", "root.inner", "logo", "legal", "links", "privacy", "terms"]);
});

test("the header draws its groups in their order", () => {
  const html = draw(<SiteHeader brand={brand} header={{ ...header, _edits: { brand: { order: ["prepared", "logo", "divider", "accountLogo"] }, actions: { order: ["ctaArea", "nav"] } } }} href={href} />);
  const at = keys(html);
  assert.ok(at.indexOf("prepared") < at.indexOf("logo"), at.join(","));
  assert.ok(at.indexOf("ctaArea") < at.indexOf("nav"), at.join(","));
});

test("an order with unknown and missing keys keeps the rest in place", () => {
  const brandGroup = (order: string[]) =>
    keys(draw(<SiteHeader brand={brand} header={{ ...header, _edits: { brand: { order } } }} href={href} />)).filter((key) => ["logo", "divider", "accountLogo", "prepared"].includes(key));
  assert.deepEqual(brandGroup(["accountLogo", "ghost"]), ["logo", "divider", "accountLogo", "prepared"]);
  assert.deepEqual(brandGroup(["prepared", "logo"]), ["prepared", "divider", "accountLogo", "logo"]);
});

test("the footer draws its parts and its links in their order", () => {
  const at = keys(draw(<SiteFooter brand={brand} footer={{ ...footer, _edits: { "root.inner": { order: ["links", "legal", "logo"] }, links: { order: ["terms", "privacy"] } } }} href={href} />));
  assert.deepEqual(at, ["root", "root.inner", "links", "terms", "privacy", "legal", "logo"]);
});

test("a hidden part and the shell's own box are styled through the scope on the header itself", () => {
  const html = draw(<SiteHeader brand={brand} header={{ ...header, _edits: { root: { fill: { hex: "#112233", opacity: 100 } }, logo: { hidden: true } } }} href={href} />);
  assert.match(html, /\[data-clue-section="shell-header"\]\[data-clue-el="root"\],\[data-clue-section="shell-header"\] \[data-clue-el="root"\]\{background-color:#112233FF !important/);
  assert.match(html, /\[data-clue-section="shell-header"\] \[data-clue-el="logo"\]\{display:none !important\}/);
});

test("kit.Card and kit.Image take the agent's name, and only a valid one; kit.Shell is a section box", () => {
  const kit = makeKit(href, brand);
  assert.deepEqual(keys(draw(<>{kit.Card({ el: "cards.0", children: "x" })}{kit.Card({ el: "cards.1", href: "/x", children: "y" })}</>)), ["cards.0", "cards.1"]);
  assert.deepEqual(keys(draw(kit.Card({ el: 'x" onclick="', children: "x" }))), []);
  assert.deepEqual(keys(draw(kit.Image({ src: "/brands/photo.png", el: "photo" }))), ["photo"]);
  assert.deepEqual(keys(draw(kit.Image({ src: "/brands/photo.png", el: "a b" }))), []);
  assert.deepEqual(keys(draw(kit.Shell({ surface: "page", children: "x" }))), ["root", "root.inner"]);
});

test("kit.Eyebrow and kit.Link take the agent's name, and only a valid one", () => {
  const kit = makeKit(href, brand);
  assert.deepEqual(keys(draw(<>{kit.Eyebrow({ children: "E", el: "kicker" })}{kit.Link({ href: "/x", children: "Read", el: "more" })}</>)), ["kicker", "more"]);
  assert.deepEqual(keys(draw(kit.Link({ href: "/x", children: "Read", el: '"]{}x' }))), []);
  assert.deepEqual(keys(draw(kit.Eyebrow({ children: "E" }))), []);
});

const clone = (html: string, slots: Clone["slots"] = {}): Clone => ({
  id: "frag_0000000000000000", role: "section", label: "Test", page_url: "https://seller.example/", section_index: 0,
  wrapper_class: "lumen-frag-test", html, css: "", slots,
});

test("a clone's text elements are keyed by their place in the captured markup; inline children are not", () => {
  const html = fillClone(clone("<div><p>One</p><p>Two <b>bold</b></p><img src=\"/x.png\"><div><span>Three</span></div></div>"));
  // Plan 4: the boxes and the image are keyed too, by the same paths.
  assert.deepEqual(keys(html), ["0", "0.0", "0.1", "0.2", "0.3", "0.3.0"]);
  assert.ok(html.includes("<b>bold</b>"), "the inline child stays unkeyed");
});

test("hiding a slot never shifts another element's key", () => {
  const captured = "<div><p data-lumen-slot=\"lead\">One</p><p>Two</p></div>";
  const slots = { lead: { kind: "visibility" as const, fallback: true } };
  assert.deepEqual(keys(fillClone(clone(captured, slots))), ["0", "0.0", "0.1"]);
  assert.deepEqual(keys(fillClone(clone(captured, slots), { lead: false })), ["0", "0.1"]);
});

test("a text slot keeps its key when its words are replaced, even when they sat inside inline tags", () => {
  const captured = "<h1 data-lumen-slot=\"headline\"><span>Old</span> words</h1>";
  const slots = { headline: { kind: "text" as const, fallback: "Old words" } };
  assert.deepEqual(keys(fillClone(clone(captured, slots))), ["0"]);
  const filled = fillClone(clone(captured, slots), { headline: "New words" });
  assert.deepEqual(keys(filled), ["0"]);
  assert.ok(filled.includes(">New words</h1>"), filled);
});

test("script, style and svg text is never keyed; an svg is keyed as a whole (plan 4)", () => {
  assert.deepEqual(keys(fillClone(clone("<div><style>p{}</style><svg><text>x</text></svg><p>Shown</p></div>"))), ["0", "0.1", "0.2"]);
});

// Plan 4: every element of a copied section is keyed, so its boxes can be styled and moved.
test("keys are unchanged for text and buttons when boxes are keyed", () => {
  const before = JSON.parse(readFileSync(new URL("./fixtures/clone-text-keys.json", import.meta.url), "utf8")) as Record<string, [string, string, string][]>;
  for (const [id, entries] of Object.entries(before)) {
    const root = parse(fillClone(brand.clones[id]));
    for (const [key, tag, words] of entries) {
      const element = root.querySelectorAll("[data-clue-el]").find((el) => el.getAttribute("data-clue-el") === key);
      assert.ok(element, `${id}: ${key} is still keyed`);
      assert.equal(element.tagName.toLowerCase(), tag, `${id}: ${key} is the same element`);
      assert.equal(element.text.replace(/\s+/g, " ").trim().slice(0, 60), words, `${id}: ${key} holds the same words`);
    }
  }
});

test("wrapper divs, images, pictures and svgs are keyed by path; scripts, styles, noscripts and templates are not", () => {
  const html = fillClone(clone('<div><div><p>One</p></div><img src="/x.png"><svg><path d="M0"/></svg><script>x</script><picture><img src="/y.png"></picture><noscript>n</noscript><span></span></div>'));
  assert.deepEqual(keys(html), ["0", "0.0", "0.0.0", "0.1", "0.2", "0.4", "0.6"]);
});

// Plan 3: every button is a box key and a label key.
test("our sections' buttons and the header's are keyed as a box and a label", () => {
  const feature = draw(sections.FeatureSplit.render({ id: "f", surface: "page", eyebrow: "", heading: "H", headingRole: "title", body: "B", image: "", imageSide: "left", buttonLabel: "Go", buttonHref: "/", buttonLook: "" } as never));
  assert.deepEqual(keys(feature), ["root", "root.inner", "row", "column", "heading", "body", "button", "button.label"]);
  const header = { preparedFor: "Carmel", accountLogo: "", ctaLabel: "Book", ctaHref: "/", nav: [] };
  assert.deepEqual(keys(draw(<SiteHeader brand={brand} header={header} href={href} />)), ["root", "root.inner", "brand", "logo", "divider", "prepared", "preparedFor", "actions", "ctaArea", "cta", "cta.label"]);
});

test("kit.Button takes the agent's name for its box and label, and only a valid one", () => {
  const kit = makeKit(href, brand);
  assert.deepEqual(keys(draw(kit.Button({ label: "Go", href: "/", surface: "page", el: "cta" } as never))), ["cta", "cta.label"]);
  assert.deepEqual(keys(draw(kit.Button({ label: "Go", href: "/", surface: "page", el: '"]{x' } as never))), []);
});

test("a clone's button is keyed by its place, and its words keep their own key", () => {
  const html = fillClone(clone('<div><a class="btn" href="/demo"><svg><path d="M0"/></svg><span>Book</span></a><p>Text</p><a href="/x">Plain words</a><a class="card" href="/c"><div><h3>Card</h3></div></a></div>'));
  // Plan 4: every element is keyed (the icon whole, the card link as a box); which keyed link is a
  // button is the frame's call (dom.ts isButtonElement), and the card link holds a block, so it is none.
  assert.deepEqual(keys(html), ["0", "0.0", "0.0.0", "0.0.1", "0.1", "0.2", "0.3", "0.3.0", "0.3.0.0"]);
});

test("a link holding an image, or more than one text, is no button: its texts keep their own keys (review 5)", () => {
  const html = fillClone(clone('<div><a class="card" href="/c"><img src="/x.png"><span>Card title</span><span>Desc</span></a><a class="btn" href="/d"><span>Book</span><span>now</span></a></div>'));
  // Plan 4: both links are keyed as boxes; neither is a button (an image; two texts), so each text
  // keeps its own key and the frame selects them as texts.
  assert.deepEqual(keys(html), ["0", "0.0", "0.0.0", "0.0.1", "0.0.2", "0.1", "0.1.0", "0.1.1"]);
});

import { rich } from "../src/rich-node";

test("a button's words never draw a link inside the button, even from an agent's rich prop (review 1)", () => {
  const kit = makeKit((value) => value, garner());
  const html = draw(kit.Button({ label: rich('Book <a href="/analysis">now</a> <strong>today</strong>', (value) => value), href: "/book", surface: "page", el: "cta" }));
  assert.equal((html.match(/<a\b/g) ?? []).length, 1, html);
  assert.match(html, /Book now <strong>today<\/strong>/);
});

import { StoredProps } from "../src/sections";

test("in the editor a button whose stored words are empty is not drawn, as on the published page", () => {
  const widget = <em>in-place editor</em>;
  const inEditor = (stored: Record<string, unknown>, node: ReactNode) => draw(<StoredProps.Provider value={stored}>{node}</StoredProps.Provider>);
  const kit = makeKit((value) => value, garner());
  const ours = sections.CtaBand.render({ id: "c", surface: "brand", heading: "H", body: "", buttonLabel: widget, buttonHref: "/", buttonLook: "" } as never);
  assert.doesNotMatch(inEditor({ id: "c", buttonLabel: "" }, ours), /brand-btn/, "our section's empty button");
  assert.match(inEditor({ id: "c", buttonLabel: "Book" }, ours), /brand-btn/);
  assert.doesNotMatch(inEditor({ id: "a", cta: "" }, kit.Button({ label: widget, href: "/", surface: "page", el: "cta" })), /brand-btn/, "an agent button named after its empty prop");
  assert.match(inEditor({ id: "a", ctaText: "Book" }, kit.Button({ label: widget, href: "/", surface: "page", el: "cta" })), /brand-btn/, "an agent button named apart from its words' prop stays");
  assert.doesNotMatch(inEditor({ id: "c" }, ours), /brand-btn/, "our section with no button words at all");
  assert.match(draw(kit.Button({ label: "Book", href: "/", surface: "page", el: "cta" })), /brand-btn/, "a published page draws from its props");
});
