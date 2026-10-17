// Review finding S1-3 (plan 2, Task 1): the catalog, the save check and the renderer read a cloned
// section's text one way — `replaceableTexts` — so a replacement the check accepts is always applied,
// and text copied from the catalog is always accepted.
import assert from "node:assert/strict";
import { test } from "node:test";
import { buildCatalog } from "../src/catalog";
import type { Clone } from "../src/clone";
import { fillClone, replaceableTexts } from "../src/clone";
import { validateSite } from "../src/validate";
import { garner } from "./fixtures/garner";

const html = [
  "<div>",
  "<h2>Care &amp; coverage</h2>",
  "<p>Top Providers.<br>Bottom line results.</p>",
  "<p>Plans that <b>actually</b> work</p>",
  "<p>\n      Lower spend in year one. No plan changes.\n    </p>",
  "<p data-lumen-slot=\"lead\">Slot words</p>",
  "<style>p{}</style>",
  "</div>",
].join("");
const clone: Clone = {
  id: "frag_00000000000000aa", role: "section", label: "Text probe", page_url: "https://seller.example/", section_index: 0,
  wrapper_class: "lumen-frag-probe", html, css: "", slots: { lead: { kind: "text", fallback: "Slot words" } },
};

test("the replaceable texts are each text node outside a text slot, decoded and collapsed", () => {
  assert.deepEqual(replaceableTexts(clone), [
    "Care & coverage",
    "Top Providers.",
    "Bottom line results.",
    "Plans that",
    "actually",
    "work",
    "Lower spend in year one. No plan changes.",
  ]);
});

test("the catalog lists exactly the replaceable texts, decoded", () => {
  const brand = garner();
  brand.clones = { [clone.id]: clone };
  const card = buildCatalog(brand, "Garner Health")[`catalog/clones/${clone.id}.md`];
  for (const text of replaceableTexts(clone)) assert.ok(card.includes(`- "${text}"`), text);
  assert.ok(!card.includes("&amp;"), "no HTML codes in the catalog");
});

function check(find: string): string[] {
  const brand = garner();
  brand.clones = { [clone.id]: clone };
  const page = { root: { props: {} }, content: [{ type: "ClonedSection", props: { id: "c1", fragmentId: clone.id, slots: {}, replacements: [{ find, replace: "NEW" }], links: [] } }] };
  const shell = { header: { preparedFor: "", accountLogo: "", ctaLabel: "", ctaHref: "", nav: [] }, footer: { legal: "", privacyHref: "", termsHref: "" } };
  return validateSite({ pages: { "/": page }, shell }, brand, {}).errors.filter((error) => error.includes("replacements"));
}

test("every replaceable text is accepted, and the renderer applies it", () => {
  for (const find of replaceableTexts(clone)) {
    assert.deepEqual(check(find), [], find);
    const out = fillClone(clone, {}, [{ find, replace: "NEW" }]);
    assert.ok(out.includes("NEW"), `${find} was not applied: ${out}`);
  }
});

test("the copied text may differ in spacing: it is matched collapsed", () => {
  const find = "  Lower spend in year one.   No plan changes. ";
  assert.deepEqual(check(find), []);
  assert.ok(fillClone(clone, {}, [{ find, replace: "NEW" }]).includes(">\n      NEW\n    <"), "the node keeps its own surrounding whitespace");
});

test("a phrase the renderer cannot replace is refused: wrapped, partial, bold-spanning, or inside a slot", () => {
  for (const find of ["Top Providers. Bottom line results.", "Lower spend", "Plans that actually work", "Slot words", "Care &amp; coverage"]) {
    const errors = check(find);
    assert.equal(errors.length, 1, find);
    assert.match(errors[0], /is not text in frag_00000000000000aa; use exact text from "Other visible text"/);
  }
});

test("a replacement's words are written as text, never as markup", () => {
  const out = fillClone(clone, {}, [{ find: "work", replace: "<b>x</b> & y" }]);
  assert.ok(out.includes("&lt;b&gt;x&lt;/b&gt; &amp; y"), out);
});
