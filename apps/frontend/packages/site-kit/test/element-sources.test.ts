// Plan 2, Task 6: for a selected element, where its rich words are stored and where its link is
// written — the facts the frame sends with a selection.
import assert from "node:assert/strict";
import { test } from "node:test";
import { z } from "zod";
import type { Clone } from "../src/clone";
import { cloneLinkAt } from "../src/clone";
import { ownLinkSource, richSourceOf } from "../src/rich-props";
import { garner } from "./fixtures/garner";

const clone: Clone = {
  id: "frag_00000000000000dd", role: "section", label: "Cards", page_url: "https://seller.example/", section_index: 0,
  wrapper_class: "w", css: "",
  html: '<div><a href="/demo">Book</a><a href="/demo"><span>Again</span></a><a data-lumen-slot="cta" href="/start">Start</a><p>Text</p></div>',
  slots: { cta: { kind: "href", fallback: "/start" } },
};

test("a clone's link is found by its element key, with its captured address and whether others share it", () => {
  assert.deepEqual(cloneLinkAt(clone, "0.0"), { href: "/demo", slot: null, shared: true });
  assert.deepEqual(cloneLinkAt(clone, "0.1.0"), { href: "/demo", slot: null, shared: true }, "text inside a link");
  assert.deepEqual(cloneLinkAt(clone, "0.2"), { href: "/start", slot: "cta", shared: false });
  assert.equal(cloneLinkAt(clone, "0.3"), null, "not a link");
  assert.equal(cloneLinkAt(clone, "9"), null);
});

test("our sections' and the shell's own links are written in a prop beside a new-tab prop", () => {
  assert.deepEqual(ownLinkSource("ProofCard", "linkLabel"), { kind: "prop", href: "linkHref", newTab: "linkNewTab" });
  assert.deepEqual(ownLinkSource("SiteHeader", "nav.2"), { kind: "prop", href: "nav.2.href", newTab: "nav.2.newTab" });
  assert.deepEqual(ownLinkSource("SiteFooter", "privacy"), { kind: "prop", href: "privacyHref", newTab: "privacyNewTab" });
  assert.deepEqual(ownLinkSource("SiteFooter", "terms"), { kind: "prop", href: "termsHref", newTab: "termsNewTab" });
  assert.equal(ownLinkSource("ProofCard", "heading"), null);
});

const agentSchema = z.toJSONSchema(z.object({ id: z.string(), surface: z.string(), title: z.string().meta({ edit: "inline" }), cards: z.array(z.object({ body: z.string().meta({ edit: "inline" }) })) }));

test("an element's words are rich where our section draws a rich prop, or the agent named it after an inline prop", () => {
  const brand = garner();
  assert.deepEqual(richSourceOf({ type: "ProofCard", props: {} }, "heading", brand, () => undefined), { prop: "heading" });
  assert.equal(richSourceOf({ type: "ProofCard", props: {} }, "linkLabel", brand, () => undefined), null);
  assert.deepEqual(richSourceOf({ type: "Probe", props: {} }, "title", brand, () => agentSchema), { prop: "title" });
  assert.deepEqual(richSourceOf({ type: "Probe", props: {} }, "cards.1.body", brand, () => agentSchema), { prop: "cards.1.body" });
  assert.equal(richSourceOf({ type: "Probe", props: {} }, "kicker", brand, () => agentSchema), null, "a name that is not an inline prop");
  assert.equal(richSourceOf({ type: "ClonedSection", props: {} }, "0.1", brand, () => undefined), null, "a clone's slots are read on the canvas");
});
