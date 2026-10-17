import assert from "node:assert/strict";
import { test } from "node:test";
import type { Config } from "@puckeditor/core";
import type { ReactElement } from "react";
import { fillClone } from "../src/clone";
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
  const render = config.components.ClonedSection.render as (props: Record<string, unknown>) => ReactElement;
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
  assert.match(bare, /<video preload="metadata"><source src="\/asset-store\/1{64}"><\/video>/);
});
