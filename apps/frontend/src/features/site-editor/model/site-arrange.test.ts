// Site element inspector, plan 4: moving an element among its neighbours (spec §4.8, ruling R5) and
// hiding the header's and footer's parts (R9), as pure decisions over the app's copy of the site.
import assert from "node:assert/strict";
import { test } from "node:test";
import type { Clone } from "@clue/site-kit";
import { componentProps } from "@clue/site-kit/editor-site";
import type { SiteDocument } from "@clue/site-kit/site-document";
import { FIXED_MOVE, arrangeState, commitHidden, commitMove, hideState, moveWrite, remapItemKeys } from "./site-arrange";

const site = (content: { type: string; props: Record<string, unknown> }[], shell: object | null = null) =>
  ({ id: "doc", title: "A", theme: {}, agent_sections: {}, shell, pages: { "/": { root: { props: { title: "Home" } }, content } } }) as unknown as SiteDocument;

/** Plan 6: the header and footer are section entries. */
const shellOf = (header: Record<string, unknown>, type = "SiteHeader") => ({
  header: { type, props: { id: "header", ...header } },
  footer: { type: "SiteFooter", props: { id: "footer", legal: "", privacyHref: "", termsHref: "" } },
});

const stats = () =>
  site([
    {
      type: "StatsBand",
      props: {
        id: "proof", surface: "page",
        stats: [{ value: "7%", label: "less" }, { value: "2x", label: 'more <span data-s="stats.1.label~1">care</span>' }],
        _edits: { "stats.1.value": { color: { hex: "#0F59B0", opacity: 100 } }, "stats.1.label~1": { fontWeight: 700 }, "stats.0": { fill: { hex: "#FFFFFF", opacity: 100 } } },
      },
    },
  ]);
const proof = { componentId: "proof", componentType: "StatsBand", target: "/" };
const statArrange = { item: "stats.1", parent: "stats", siblings: ["stats.0", "stats.1"] };

test("moving stat 1 up swaps the array and carries its edits and styled spans with it", () => {
  const moved = commitMove(stats(), proof, statArrange, "up");
  assert.ok(moved);
  assert.equal(moved.key, "stats.0", "the selection follows the moved stat");
  const props = componentProps(moved.site, "/", "proof")!;
  assert.deepEqual(props.stats, [{ value: "2x", label: 'more <span data-s="stats.0.label~1">care</span>' }, { value: "7%", label: "less" }]);
  assert.deepEqual(props._edits, {
    "stats.0.value": { color: { hex: "#0F59B0", opacity: 100 } },
    "stats.0.label~1": { fontWeight: 700 },
    "stats.1": { fill: { hex: "#FFFFFF", opacity: 100 } },
  });
});

test("remapItemKeys renames only whole keys under the two items (stats.1 never touches stats.10)", () => {
  const props = { stats: [{}, {}], _edits: { "stats.1": { gap: 4 }, "stats.10": { gap: 8 }, "stats.0~2": { fontWeight: 700 }, x: { order: ["stats.0", "stats.1"] } } };
  assert.deepEqual(remapItemKeys(props, "stats", 0, 1)._edits, { "stats.0": { gap: 4 }, "stats.10": { gap: 8 }, "stats.1~2": { fontWeight: 700 }, x: { order: ["stats.1", "stats.0"] } });
});

// Plan 6 (ruling R11): the header's menu items move through `order` (they are keyed by page); a
// template header orders like any copied section; an agent's header is fixed, as on a page.
test("moveWrite gives order for header entries of type ClonedSection and SiteHeader, and fixed for an agent's header", () => {
  const arrange = { item: "menu.team", parent: "menu", siblings: ["menu._home", "menu.team"] };
  const ours = site([], shellOf({ accountLine: "C", accountLogo: "", ctaLabel: "Go", ctaHref: "/" }));
  assert.deepEqual(moveWrite(ours, { componentId: "header", componentType: "SiteHeader", target: "shell" }, arrange), { kind: "order" });
  const moved = commitMove(ours, { componentId: "header", componentType: "SiteHeader", target: "shell" }, arrange, "up")!;
  assert.deepEqual(componentProps(moved.site, "shell", "header")!._edits, { menu: { order: ["menu.team", "menu._home"] } });
  const template = site([], shellOf({ fragmentId: clone.id, slots: {}, replacements: [], links: [] }, "ClonedSection"));
  assert.deepEqual(moveWrite(template, { componentId: "header", componentType: "ClonedSection", target: "shell" }, { item: "0.1", parent: "0", siblings: ["0.0", "0.1"] }), { kind: "order" });
  const agent = site([], shellOf({ surface: "page" }, "SiteHeaderAcme"));
  assert.deepEqual(moveWrite(agent, { componentId: "header", componentType: "SiteHeaderAcme", target: "shell" }, { item: "a", parent: "row", siblings: ["a", "b"] }), { kind: "fixed", reason: FIXED_MOVE });
});

const clone: Clone = {
  id: "frag_0000000000000000", role: "section", label: "Cards", page_url: "https://seller.example/", section_index: 0,
  wrapper_class: "lumen-frag-test", html: "<div><div><p>A</p></div><div><p>B</p></div><div><p>C</p></div></div>", css: "", slots: {},
};
const brand = { clones: { [clone.id]: clone } } as never;

test("a copied card moves by writing order on its parent; moving it back drops the order", () => {
  const copied = site([{ type: "ClonedSection", props: { id: "cards", fragmentId: clone.id, slots: {}, replacements: [], links: [] } }]);
  const sel = { componentId: "cards", componentType: "ClonedSection", target: "/" };
  const arrange = { item: "0.1", parent: "0", siblings: ["0.0", "0.1", "0.2"] };
  assert.deepEqual(moveWrite(copied, sel, arrange), { kind: "order" });
  const moved = commitMove(copied, sel, arrange, "down", brand)!;
  assert.equal(moved.key, "0.1", "a copied element keeps its key where it moves");
  assert.deepEqual(componentProps(moved.site, "/", "cards")!._edits, { "0": { order: ["0.0", "0.2", "0.1"] } });
  const back = commitMove(moved.site, sel, { ...arrange, siblings: ["0.0", "0.2", "0.1"] }, "up", brand)!;
  assert.equal(componentProps(back.site, "/", "cards")!._edits, undefined, "the captured order needs no order");
});

test("a heading in our fixed layout does not move, and says why", () => {
  const feature = site([{ type: "FeatureSplit", props: { id: "f", heading: "H", body: "B" } }]);
  const sel = { componentId: "f", componentType: "FeatureSplit", target: "/" };
  const arrange = { item: "heading", parent: "column", siblings: ["heading", "body"] };
  assert.deepEqual(moveWrite(feature, sel, arrange), { kind: "fixed", reason: FIXED_MOVE });
  assert.equal(FIXED_MOVE, "This part's place is set by the section's design; ask the agent to move it.");
  assert.equal(commitMove(feature, sel, arrange, "down"), null);
  assert.deepEqual(arrangeState(feature, { ...sel, element: { arrange } as never }), { canUp: false, canDown: false, note: FIXED_MOVE });
});

test("ends: the first cannot move up, the last cannot move down", () => {
  assert.equal(commitMove(stats(), proof, { ...statArrange, item: "stats.0" }, "up"), null);
  assert.equal(commitMove(stats(), proof, statArrange, "down"), null);
  assert.deepEqual(arrangeState(stats(), { ...proof, element: { arrange: statArrange } as never }), { canUp: true, canDown: false, note: null });
  assert.equal(arrangeState(stats(), { ...proof, element: { arrange: null } as never }), null);
});

test("hide and show a header logo; showing restores the stored header exactly; a page section offers no hide", () => {
  const start = site([], shellOf({ accountLine: "C", accountLogo: "", ctaLabel: "Go", ctaHref: "/", _edits: { logo: { borderWidth: 1 } } }));
  const header = { componentId: "header", target: "shell" };
  const hidden = commitHidden(start, header, "logo", true)!;
  assert.deepEqual(componentProps(hidden.site, "shell", "header")!._edits, { logo: { borderWidth: 1, hidden: true } });
  assert.deepEqual(hideState(hidden.site, { ...header, element: { key: "logo" } as never }), { hidden: true, part: "header" });
  const shown = commitHidden(hidden.site, header, "logo", false)!;
  assert.deepEqual(componentProps(shown.site, "shell", "header"), componentProps(start, "shell", "header"));
  assert.equal(hideState(stats(), { componentId: "proof", target: "/", element: { key: "stats.0" } as never }), null);
});

// End-of-plan review I1 and I6: the selection stays on the element the marketer selected (not the
// wrapper the move climbed to), and a second quick press builds on the first.
test("review I1: a move through a wrapper keeps the selected element's own key; an array move renames it", () => {
  const shell = site([], shellOf({ accountLine: "C", accountLogo: "", ctaLabel: "Go", ctaHref: "/" }));
  const header = { componentId: "header", componentType: "SiteHeader", target: "shell" };
  const moved = commitMove(shell, header, { item: "ctaArea", parent: "actions", siblings: ["menu", "ctaArea"] }, "up", null, "cta")!;
  assert.equal(moved.key, "cta", "still the button, not its area");
  const inside = commitMove(stats(), proof, statArrange, "up", null, "stats.1.value")!;
  assert.equal(inside.key, "stats.0.value");
});

test("review I6: commitMove returns where the element now sits among its neighbours, so a second press builds on it", () => {
  const three = site([{ type: "StatsBand", props: { id: "proof", surface: "page", stats: [{ value: "a" }, { value: "b" }, { value: "c" }] } }]);
  const first = commitMove(three, proof, { item: "stats.2", parent: "stats", siblings: ["stats.0", "stats.1", "stats.2"] }, "up")!;
  assert.deepEqual(first.arrange, { item: "stats.1", parent: "stats", siblings: ["stats.0", "stats.1", "stats.2"] });
  const second = commitMove(first.site, proof, first.arrange, "up")!;
  assert.deepEqual(componentProps(second.site, "/", "proof")!.stats, [{ value: "c" }, { value: "a" }, { value: "b" }]);
  const copied = site([{ type: "ClonedSection", props: { id: "cards", fragmentId: clone.id, slots: {}, replacements: [], links: [] } }]);
  const sel = { componentId: "cards", componentType: "ClonedSection", target: "/" };
  const once = commitMove(copied, sel, { item: "0.2", parent: "0", siblings: ["0.0", "0.1", "0.2"] }, "up", brand)!;
  assert.deepEqual(once.arrange.siblings, ["0.0", "0.2", "0.1"]);
  const twice = commitMove(once.site, sel, once.arrange, "up", brand)!;
  assert.deepEqual(componentProps(twice.site, "/", "cards")!._edits, { "0": { order: ["0.2", "0.0", "0.1"] } });
});
