import assert from "node:assert/strict";
import { test } from "node:test";
import type { Config } from "@puckeditor/core";
import type { ReactElement } from "react";
import { parse } from "node-html-parser";
import { cloneOrderOf, fillClone, type Clone } from "../src/clone";
import { makeConfig } from "../src/config";
import { garner, site } from "./fixtures/garner";

// Review finding S1-1. Puck 0.23 runs a component's resolveData on every page mount, comparing the
// item with the last one it saw for the same component id in a module-wide cache shared by every page
// and site in the frame. A cloned section's "refill when the clone changes" rule therefore reset the
// agent's copy to the seller's wording on a page switch, and the frame saved it. The real behaviour is
// pinned in the browser harness (tests/site_editor/test_editor_clone_editing.py); this pins the cause.
test("a cloned section has no load-time refill (no resolveData)", () => {
  const stored = site("garner-syracuse");
  const config = makeConfig(garner(), { cloneHtml: fillClone, mode: "page", shell: stored.shell }) as Config;
  assert.equal(config.components.ClonedSection.resolveData, undefined);
});

test("the editor's clone view is handed the markup a slot write would produce", () => {
  const stored = site("garner-syracuse");
  const CloneEditor = () => null;
  const config = makeConfig(garner(), { cloneHtml: fillClone, editor: { AssetPicker: () => null, CloneEditor }, mode: "page", shell: stored.shell }) as Config;
  const hero = stored.pages["/"].content.find((item: { props: { id: string } }) => item.props.id === "hero")!;
  const scoped = config.components.ClonedSection.render as (props: Record<string, unknown>) => ReactElement;
  // Every section draws inside the box that scopes its manual styling; the section is its child.
  // Its child is drawn from the section's edits (plan 4: a copied section's `order`).
  const render = (props: Record<string, unknown>) => (scoped(props).props as { children: (edits: object) => ReactElement }).children({});
  const element = render({ ...hero.props, puck: { isEditing: true } });
  assert.equal(element.type, CloneEditor);
  const { html, htmlFor } = element.props as { html: string; htmlFor: (key: string, value: string) => string };
  assert.match(htmlFor("headline", "A new headline"), /A new headline/);
  assert.notEqual(htmlFor("headline", "A new headline"), html);
  // An emptied text slot shows the clone's own wording, so the write leaves the markup as it would
  // be with the slot unset — the case CloneEditor redraws for (S1-4).
  const others = Object.fromEntries(Object.entries(hero.props.slots as Record<string, unknown>).filter(([key]) => key !== "headline"));
  const unset = render({ ...hero.props, slots: others, puck: { isEditing: true } });
  const unsetProps = unset.props as { html: string; htmlFor: (key: string, value: string) => string };
  assert.equal(unsetProps.htmlFor("headline", ""), unsetProps.html);
});

test("a captured video loads its metadata only, shows its poster and plays the smaller rendition", () => {
  const [video, poster, rendition, own] = ["1", "2", "3", "4"].map((c) => c.repeat(64));
  const base = { id: "frag_v", role: "hero", label: "Hero", page_url: "https://x.example/", section_index: 0,
    wrapper_class: "lumen-frag-v", css: "", slots: {}, videos: { [video]: { poster, rendition } } };
  const filled = fillClone({ ...base, html: `<video autoplay muted loop playsinline><source src="/asset-store/${video}" type="video/mp4"></video>` });
  assert.match(filled, /<video[^>]*preload="metadata"/);
  assert.match(filled, new RegExp(`<video[^>]*poster="/asset-store/${poster}"`));
  assert.match(filled, new RegExp(`<source src="/asset-store/${rendition}"`));
  // A video with its own src attribute is pointed at the rendition the same way.
  assert.match(fillClone({ ...base, html: `<video src="/asset-store/${video}"></video>` }), new RegExp(`src="/asset-store/${rendition}"`));
  // The seller's own poster: only preload changes.
  const kept = fillClone({ ...base, html: `<video poster="/asset-store/${own}"><source src="/asset-store/${video}"></video>` });
  assert.match(kept, new RegExp(`poster="/asset-store/${own}"`));
  assert.match(kept, new RegExp(`<source src="/asset-store/${video}"`));
  assert.match(kept, /preload="metadata"/);
  // Nothing known about a video: preload only.
  const bare = fillClone({ ...base, videos: undefined, html: `<video><source src="/asset-store/${video}"></video>` });
  assert.match(bare, /<video data-clue-el="0" preload="metadata"><source src="\/asset-store\/1{64}"><\/video>/);
});

// Plan 4: the order of a copied box's children, by their keys in the captured markup.
const box = (html: string, slots: Clone["slots"] = {}): Clone => ({
  id: "frag_0000000000000000", role: "section", label: "Test", page_url: "https://seller.example/", section_index: 0,
  wrapper_class: "lumen-frag-test", html, css: "", slots,
});
const childKeys = (html: string, parent: string) =>
  parse(html).querySelectorAll("[data-clue-el]").find((el) => el.getAttribute("data-clue-el") === parent)!.childNodes
    .filter((node) => (node as { tagName?: string }).tagName)
    .map((node) => (node as unknown as { getAttribute: (name: string) => string }).getAttribute("data-clue-el"));

test("order rearranges a parent's children before slots apply, and keys travel with their elements", () => {
  const clone = box('<div><div><p data-lumen-slot="headline">Old</p><p>B</p><p>C</p></div></div>', { headline: { kind: "text", fallback: "Old" } });
  const html = fillClone(clone, { headline: "New" }, [], [], { order: { "0.0": ["0.0.2", "0.0.0", "0.0.1"] } });
  assert.deepEqual(childKeys(html, "0.0"), ["0.0.2", "0.0.0", "0.0.1"]);
  assert.match(html, /<p data-clue-el="0\.0\.2">C<\/p><p data-lumen-slot="headline" data-clue-el="0\.0\.0">New<\/p><p data-clue-el="0\.0\.1">B<\/p>/);
});

test("an order naming gone keys or leaving children out keeps the others in place", () => {
  const clone = box("<ul><li>A</li><li>B</li><li>C</li><li>D</li></ul>");
  assert.deepEqual(childKeys(fillClone(clone, {}, [], [], { order: { "0": ["0.3", "ghost", "0.0"] } }), "0"), ["0.3", "0.1", "0.2", "0.0"]);
  assert.deepEqual(childKeys(fillClone(clone, {}, [], [], { order: { "0": ["ghost"] } }), "0"), ["0.0", "0.1", "0.2", "0.3"]);
  assert.deepEqual(childKeys(fillClone(clone, {}, [], [], { order: { "9.9": ["0.1", "0.0"] } }), "0"), ["0.0", "0.1", "0.2", "0.3"]);
});

test("cloneOrderOf gives a parent's keyed children in their captured order", () => {
  const clone = box("<ul><li>A</li><li>B</li></ul>");
  assert.deepEqual(cloneOrderOf(clone, "0"), ["0.0", "0.1"]);
  assert.equal(cloneOrderOf(clone, "7"), null);
});
