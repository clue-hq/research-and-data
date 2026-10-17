// Site element inspector, plan 1 Task 3: every text element a marketer can style carries a stable
// key (data-clue-el), the same in the editor and on the published page.
import assert from "node:assert/strict";
import { test } from "node:test";
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
    ["eyebrow", "heading", "intro", "stats.0.value", "stats.0.label", "stats.1.value", "stats.1.label", "source"],
  );
  assert.deepEqual(
    keys(draw(sections.FeatureSplit.render({ id: "f", surface: "page", eyebrow: "E", heading: "H", headingRole: "title", body: "B", image: "", imageSide: "left", buttonLabel: "Go", buttonHref: "/", buttonLook: "" } as never))),
    ["eyebrow", "heading", "body"],
  );
  assert.deepEqual(
    keys(draw(sections.ProofCard.render({ id: "p", surface: "card", kicker: "K", metric: "13%", metricLabel: "L", heading: "H", body: "B", source: "S", linkLabel: "Read", linkHref: "/x" } as never))),
    ["kicker", "metric", "metricLabel", "heading", "body", "source", "linkLabel"],
  );
  assert.deepEqual(
    keys(draw(sections.CtaBand.render({ id: "c", surface: "brand", heading: "H", body: "B", buttonLabel: "Go", buttonHref: "/", buttonLook: "" } as never))),
    ["heading", "body"],
  );
});

test("an empty optional text draws no element and so no key", () => {
  assert.deepEqual(
    keys(draw(sections.CtaBand.render({ id: "c", surface: "brand", heading: "H", body: "", buttonLabel: "Go", buttonHref: "/", buttonLook: "" } as never))),
    ["heading"],
  );
});

test("the header and footer name their text", () => {
  const header = { preparedFor: "Carmel Clay Schools", accountLogo: "", ctaLabel: "Go", ctaHref: "/", nav: [{ label: "Analysis", href: "/analysis" }] };
  assert.deepEqual(keys(draw(<SiteHeader brand={brand} header={header} href={href} />)), ["preparedFor", "nav.0"]);
  const footer = { legal: "© 2026", privacyHref: "/privacy", termsHref: "/terms" };
  assert.deepEqual(keys(draw(<SiteFooter brand={brand} footer={footer} href={href} />)), ["legal", "privacy", "terms"]);
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
  assert.deepEqual(keys(html), ["0.0", "0.1", "0.3.0"]);
  assert.ok(html.includes("<b>bold</b>"), "the inline child stays unkeyed");
});

test("hiding a slot never shifts another element's key", () => {
  const captured = "<div><p data-lumen-slot=\"lead\">One</p><p>Two</p></div>";
  const slots = { lead: { kind: "visibility" as const, fallback: true } };
  assert.deepEqual(keys(fillClone(clone(captured, slots))), ["0.0", "0.1"]);
  assert.deepEqual(keys(fillClone(clone(captured, slots), { lead: false })), ["0.1"]);
});

test("a text slot keeps its key when its words are replaced, even when they sat inside inline tags", () => {
  const captured = "<h1 data-lumen-slot=\"headline\"><span>Old</span> words</h1>";
  const slots = { headline: { kind: "text" as const, fallback: "Old words" } };
  assert.deepEqual(keys(fillClone(clone(captured, slots))), ["0"]);
  const filled = fillClone(clone(captured, slots), { headline: "New words" });
  assert.deepEqual(keys(filled), ["0"]);
  assert.ok(filled.includes(">New words</h1>"), filled);
});

test("script, style and svg text is never keyed", () => {
  assert.deepEqual(keys(fillClone(clone("<div><style>p{}</style><svg><text>x</text></svg><p>Shown</p></div>"))), ["0.2"]);
});
