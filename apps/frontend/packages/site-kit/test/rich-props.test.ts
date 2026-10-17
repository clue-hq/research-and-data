// Plan 2, Task 3: which props hold rich text (our sections' in-place text, the agent's inline props,
// clone text slots), how every save checks them, and the new "open in a new tab" props.
import assert from "node:assert/strict";
import { test } from "node:test";
import { z } from "zod";
import { richPropPaths, richValuesAt } from "../src/agent-props";
import { buildCatalog } from "../src/catalog";
import type { Clone } from "../src/clone";
import { RICH_PROPS } from "../src/schemas";
import { validateSite, type AgentSectionSchemas } from "../src/validate";
import { garner } from "./fixtures/garner";

const shell = (extra: { header?: object; footer?: object } = {}) => ({
  header: { preparedFor: "Carmel", accountLogo: "", ctaLabel: "Book", ctaHref: "https://garner.example/book", nav: [], ...extra.header },
  footer: { legal: "© 2026", privacyHref: "", termsHref: "", ...extra.footer },
});
const page = (content: object[]) => ({ root: { props: {} }, content });
const proof = (props: object) => ({
  type: "ProofCard",
  props: { id: "proof", surface: "card", kicker: "Customer", metric: "13%", metricLabel: "less", heading: "What they did", ...props },
});

function errorsOf(pages: Record<string, object>, agent: AgentSectionSchemas = {}, extraShell?: { header?: object; footer?: object }, brand = garner()) {
  return validateSite({ pages, shell: shell(extraShell) }, brand, agent).errors;
}

test("our sections' in-place text is rich, except link and button labels", () => {
  assert.deepEqual(RICH_PROPS, {
    StatsBand: ["eyebrow", "heading", "intro", "source"],
    FeatureSplit: ["eyebrow", "heading", "body"],
    ProofCard: ["kicker", "metric", "metricLabel", "heading", "body", "source"],
    CtaBand: ["heading", "body"],
  });
});

test("rich text in our sections is checked against the grammar, at its place", () => {
  assert.deepEqual(errorsOf({ "/": page([proof({ heading: 'Top <strong>results</strong> <span data-s="heading~1">here</span>' })]) }), []);
  const errors = errorsOf({ "/": page([proof({ heading: '<div class="x">Top</div>' })]) });
  assert.deepEqual(errors, ["page.content.0(proof).heading: <div> is not allowed in text"]);
  assert.deepEqual(errorsOf({ "/": page([proof({ linkLabel: "<strong>Read</strong>", linkHref: "/" })]) }).length, 0, "a link label is plain text: markup there is just characters");
});

test("a link inside rich text must reach a page of this site, like every other link", () => {
  const errors = errorsOf({ "/": page([proof({ body: 'See <a href="/missing">the analysis</a>' })]) });
  assert.equal(errors.length, 1);
  assert.match(errors[0], /^page\.content\.0\(proof\)\.body: links to \/missing, which is not a page of this site/);
  assert.deepEqual(errorsOf({ "/": page([proof({ body: 'See <a href="/" data-new-tab="">home</a>' })]) }), []);
});

test("the new 'open in a new tab' props are accepted where links live, and only as true or false", () => {
  assert.deepEqual(errorsOf({ "/": page([proof({ linkLabel: "Read", linkHref: "/", linkNewTab: true })]) }), []);
  assert.deepEqual(
    errorsOf({ "/": page([]) }, {}, { header: { nav: [{ label: "Home", href: "/", newTab: true }] }, footer: { privacyHref: "https://x.com/p", privacyNewTab: true, termsNewTab: false } }),
    [],
  );
  const errors = errorsOf({ "/": page([proof({ linkNewTab: "yes" })]) });
  assert.equal(errors.length, 1);
  assert.match(errors[0], /linkNewTab/);
});

const agentJson = z.toJSONSchema(
  z.object({
    id: z.string(),
    surface: z.string(),
    headline: z.string().meta({ edit: "inline" }),
    note: z.string(),
    cards: z.array(z.object({ title: z.string().meta({ edit: "inline" }), href: z.string() }).strict()),
  }).strict(),
);

test("an agent section's rich props are the ones it marked for editing in place", () => {
  assert.deepEqual(richPropPaths(agentJson as never), ["headline", "cards.*.title"]);
  assert.deepEqual(
    richValuesAt({ headline: "H", note: "<b>n</b>", cards: [{ title: "A", href: "/" }, { title: "B", href: "/" }] }, richPropPaths(agentJson as never)),
    [{ path: "headline", value: "H" }, { path: "cards.0.title", value: "A" }, { path: "cards.1.title", value: "B" }],
  );
});

test("the save check reads an agent section's rich props from its stored schema", () => {
  const agent: AgentSectionSchemas = { Probe: { schema: z.fromJSONSchema(agentJson as never), propsSchema: agentJson } };
  const item = (props: object) => ({ type: "Probe", props: { id: "p", surface: "page", headline: "H", note: "", cards: [], ...props } });
  assert.deepEqual(errorsOf({ "/": page([item({ headline: "Top <em>now</em>" })]) }, agent), []);
  assert.deepEqual(errorsOf({ "/": page([item({ cards: [{ title: "<img src=x>", href: "/" }] })]) }, agent), [
    "page.content.0(p).cards.0.title: <img> is not allowed in text",
  ]);
  assert.deepEqual(errorsOf({ "/": page([item({ note: "<b>not rich</b>" })]) }, agent), [], "an unmarked prop is plain text");
});

const clone: Clone = {
  id: "frag_00000000000000bb", role: "section", label: "Hero", page_url: "https://seller.example/", section_index: 0,
  wrapper_class: "lumen-frag-hero", html: '<div><h1 data-lumen-slot="headline">Top</h1><a href="/demo">Demo</a></div>', css: "",
  slots: { headline: { kind: "text", fallback: "Top" } },
};

test("a clone's text slots are rich; its new-tab links are named by element key", () => {
  const brand = garner();
  brand.clones = { [clone.id]: clone };
  const cloned = (props: object) => ({ type: "ClonedSection", props: { id: "hero", fragmentId: clone.id, slots: {}, replacements: [], links: [], ...props } });
  assert.deepEqual(errorsOf({ "/": page([cloned({ slots: { headline: 'Top <span data-s="0~1">results</span>' }, newTab: ["1"] })]) }, {}, undefined, brand), []);
  assert.deepEqual(errorsOf({ "/": page([cloned({ slots: { headline: "<script>x</script>" } })]) }, {}, undefined, brand), [
    "page.content.0(hero).slots.headline: <script> is not allowed in text",
  ]);
  const bad = errorsOf({ "/": page([cloned({ newTab: ['"]{x'] })]) }, {}, undefined, brand);
  assert.equal(bad.length, 1);
  assert.match(bad[0], /newTab/);
});

test("the catalog names rich fields as rich text", () => {
  const sections = buildCatalog(garner(), "Garner Health")["catalog/sections.md"];
  assert.match(sections, /\| `heading` \| rich text \| yes \|/);
  assert.match(sections, /\| `linkLabel` \| string \| no \|/);
  assert.match(sections, /\| `linkNewTab` \| boolean \| no \|/);
});

// Plan 3: button labels are rich without links; a clone text slot inside a captured link is too.
import { RICH_PROPS_NO_LINKS } from "../src/schemas";

test("button labels take rich text without links, in our sections, the header and a clone's link", () => {
  assert.deepEqual(RICH_PROPS_NO_LINKS, { FeatureSplit: ["buttonLabel"], CtaBand: ["buttonLabel"] });
  const cta = (props: object) => ({ type: "CtaBand", props: { id: "cta", surface: "brand", heading: "H", buttonLabel: "Go", buttonHref: "/", ...props } });
  assert.deepEqual(errorsOf({ "/": page([cta({ buttonLabel: "Book <strong>now</strong>", buttonNewTab: true })]) }), []);
  assert.deepEqual(errorsOf({ "/": page([cta({ buttonLabel: 'Book <a href="/">now</a>' })]) }), ["page.content.0(cta).buttonLabel: a button's words may not hold a link"]);
  assert.deepEqual(errorsOf({ "/": page([]) }, {}, { header: { ctaLabel: 'Go <a href="/">x</a>' } }), ["shell.header.ctaLabel: a button's words may not hold a link"]);
  assert.deepEqual(errorsOf({ "/": page([]) }, {}, { header: { ctaLabel: "Go <em>now</em>", ctaNewTab: true } }), []);
  const brand = garner();
  const inLink: Clone = { ...clone, id: "frag_00000000000000be", html: '<div><a href="/demo"><span data-lumen-slot="label">Book</span></a></div>', slots: { label: { kind: "text", fallback: "Book" } } };
  brand.clones = { [inLink.id]: inLink };
  const cloned = { type: "ClonedSection", props: { id: "c", fragmentId: inLink.id, slots: { label: 'Book <a href="/">now</a>' }, replacements: [], links: [] } };
  assert.deepEqual(errorsOf({ "/": page([cloned]) }, {}, undefined, brand), ["page.content.0(c).slots.label: a button's words may not hold a link"]);
});
