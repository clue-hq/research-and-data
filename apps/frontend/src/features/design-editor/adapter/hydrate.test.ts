import assert from "node:assert/strict";
import test from "node:test";
import type { WebNode } from "../engine/webDocuments";
import {
  HARVESTED_HIDDEN_CONTAINER_V52,
  HARVESTED_ICON_V56,
  HARVESTED_PAGE,
  HARVESTED_PAGE_ROOT_V47,
} from "./__fixtures__/web-nodes";
import { hydrateInspectorState, inspectorSelectionFor } from "./hydrate";

// W2.2: the hydration adapter IS the contract's §1 mapping table — every case
// here cites its row. Fixtures are real harvested WebNode snapshots (see
// __fixtures__/web-nodes.ts provenance header), one per inspector schema.

function node(id: string): WebNode {
  const found = HARVESTED_PAGE.nodes[id];
  assert.ok(found, `fixture node ${id} missing`);
  return found;
}

function hydrate(id: string) {
  const n = node(id);
  return hydrateInspectorState(n, n.classes);
}

// ── kind → schema (the plan's map; §5 fallback; 18b icon partition) ─────────

test("kind → schema: every harvested kind resolves per the contract", () => {
  const root = HARVESTED_PAGE.page_root;
  assert.deepEqual(inspectorSelectionFor(node("headline"), root), {
    selection: "text",
    layoutOnly: false,
  });
  assert.deepEqual(inspectorSelectionFor(node("fimg"), root), {
    selection: "image",
    layoutOnly: false,
  });
  assert.deepEqual(inspectorSelectionFor(node("cta"), root), {
    selection: "button",
    layoutOnly: false,
  });
  // 18b: icon selections show Layout/padding only.
  assert.deepEqual(inspectorSelectionFor(node("ficon"), root), {
    selection: "icon",
    layoutOnly: true,
  });
  assert.deepEqual(inspectorSelectionFor(node("fgrid"), root), {
    selection: "container",
    layoutOnly: false,
  });
  assert.deepEqual(inspectorSelectionFor(node("hero"), root), {
    selection: "section",
    layoutOnly: false,
  });
});

test("the page root hydrates as the canvas schema", () => {
  assert.deepEqual(inspectorSelectionFor(node("root"), HARVESTED_PAGE.page_root), {
    selection: "canvas",
    layoutOnly: false,
  });
});

test("embed (and any unknown kind) falls back to layout-only (§5)", () => {
  const root = HARVESTED_PAGE.page_root;
  assert.deepEqual(inspectorSelectionFor(node("fembed"), root), {
    selection: "container",
    layoutOnly: true,
  });
  const unknown = { ...node("fembed"), kind: "carousel" };
  assert.deepEqual(inspectorSelectionFor(unknown, root), {
    selection: "container",
    layoutOnly: true,
  });
});

// ── text schema ─────────────────────────────────────────────────────────────

test("text: size/weight/align/color hydrate per §1 rows 4-7", () => {
  // sub: "text-lg text-slate-300 text-center max-w-xl"
  const state = hydrate("sub");
  assert.equal(state.fontSize, "18"); // lg → 18 (row 5 ramp)
  assert.equal(state.horizontalAlignment, "center"); // row 7
  assert.equal(state.tokenTextColor, "Slate-300"); // row 4, token name
});

test("text: a ramp size beyond the contract mapping is omitted, weight maps", () => {
  // headline: "text-5xl font-bold text-white text-center" — 5xl has no UI slot
  // (§6(5): the select's options end at 3xl/32).
  const state = hydrate("headline");
  assert.ok(!("fontSize" in state));
  assert.equal(state.fontWeight, "Bold"); // row 6
  assert.equal(state.tokenTextColor, "White");
  assert.equal(state.horizontalAlignment, "center");
});

// ── button schema ───────────────────────────────────────────────────────────

test("button: variant/link/colors/weight/padding hydrate per §1 rows 15-17", () => {
  // cta: "rounded-full bg-white text-slate-900 px-6 py-3 font-semibold",
  // variant primary, href "#", new_tab false.
  const state = hydrate("cta");
  assert.equal(state.buttonLabel, "Primary"); // row 16 style select
  assert.equal(state.url, "#"); // row 15
  assert.equal(state.openInNewTab, false);
  assert.equal(state.tokenBackgroundColor, "White"); // row 17
  assert.equal(state.tokenTextColor, "Slate-900");
  assert.equal(state.fontWeight, "Semi Bold");
  assert.deepEqual(state.padding, {
    bottom: "3",
    left: "6",
    right: "6",
    top: "3",
  }); // R3: two-axis boxes
});

// ── image schema ────────────────────────────────────────────────────────────

test("image: mode and link hydrate per §1 rows 11/13", () => {
  // fimg: "object-cover", href https://example.com, new_tab true.
  const state = hydrate("fimg");
  assert.equal(state.fillMode, "Fill"); // cover → Fill
  assert.equal(state.url, "https://example.com");
  assert.equal(state.openInNewTab, true);
});

// ── icon (layout-only) ──────────────────────────────────────────────────────

test("icon: padding hydrates (the only live sections per 18b)", () => {
  // ficon: "px-2 py-2 text-primary"
  const state = hydrate("ficon");
  assert.deepEqual(state.padding, {
    bottom: "2",
    left: "2",
    right: "2",
    top: "2",
  });
  assert.equal(state.tokenTextColor, "Primary");
});

test("18b + R3: an icon with one padding axis states the other as a truthful zero", () => {
  // ficon @56: "px-2 text-primary" — no py- utility means NO padding on that
  // axis, so the trimmed schema's one live section must show 0, never the
  // dummy's fixture default.
  const icon = HARVESTED_ICON_V56.nodes.ficon;
  assert.ok(icon);
  const state = hydrateInspectorState(icon, icon.classes);
  assert.deepEqual(state.padding, {
    bottom: "0",
    left: "2",
    right: "2",
    top: "0",
  });
  // 18b hides the icon's color/size/stroke sections, so nothing the schema
  // renders reads these — the authored `text-primary` is the page's own
  // styling, and the icon name stays agent-authored (no `iconName` state).
  assert.equal(state.iconName, undefined);
  assert.equal(state.iconSize, undefined);
  assert.equal(state.iconStroke, undefined);
});

// ── container schema ────────────────────────────────────────────────────────

test("container: display/gap/colors/padding hydrate per §1 rows 19-20", () => {
  // fgrid: "grid grid-cols-3 gap-6 px-4 py-2 bg-card text-dark"
  const state = hydrate("fgrid");
  assert.equal(state.layoutMode, "Grid"); // row 20
  assert.equal(state.gap, "6");
  assert.equal(state.tokenBackgroundColor, "Card"); // row 19
  assert.equal(state.tokenTextColor, "Dark");
  assert.deepEqual(state.padding, {
    bottom: "2",
    left: "4",
    right: "4",
    top: "2",
  });
});

test("a one-axis padding fills the other axis with the truthful zero", () => {
  // No py utility present means zero vertical padding — never the dummy's
  // fixture default.
  const state = hydrateInspectorState(node("fgrid"), "px-4");
  assert.deepEqual(state.padding, {
    bottom: "0",
    left: "4",
    right: "4",
    top: "0",
  });
});

// ── section schema ──────────────────────────────────────────────────────────

test("section: direction/gap hydrate per §1 row 22; absent wrap is a truthful No", () => {
  // hero: "flex flex-col items-center gap-6 py-24 px-8 bg-slate-900"
  const state = hydrate("hero");
  assert.equal(state.direction, "vertical"); // col
  assert.equal(state.gap, "6");
  assert.equal(state.layoutMode, "Flex");
  assert.equal(state.tokenBackgroundColor, "Slate-900");
  // W4.4 fix (controller ruling 2026-08-18): no flex-wrap utility has a KNOWN
  // real behavior — CSS defaults to nowrap — so this is R3's truthful-value
  // pattern (padding's truthful zeros), not §6(5)'s unknown-value omission.
  assert.equal(state.wrap, false);
});

test("section: an explicit wrap value hydrates truthfully either way", () => {
  const wrapping = hydrateInspectorState(node("hero"), "flex flex-wrap gap-6");
  assert.equal(wrapping.wrap, true);
  const notWrapping = hydrateInspectorState(node("hero"), "flex flex-nowrap gap-6");
  assert.equal(notWrapping.wrap, false);
  // `flex-wrap-reverse` still wraps.
  const reverse = hydrateInspectorState(node("hero"), "flex flex-wrap-reverse");
  assert.equal(reverse.wrap, true);
});

test("the truthful-No default is the section schema's own (it alone shows Wrap)", () => {
  // A container with no flex-wrap keeps the dummy default: row 21 gives the
  // container no Wrap control at all (§7 item 1, future work), so there is
  // nothing to state truthfully.
  const container = hydrateInspectorState(node("fgrid"), "grid gap-6");
  assert.ok(!("wrap" in container));
});

// ── visibility (row 40) and the classes override parameter ─────────────────

test("display hidden hydrates Hide + invisible (rows 20/40)", () => {
  const state = hydrateInspectorState(node("fgrid"), "hidden gap-2");
  assert.equal(state.layoutMode, "Hide");
  assert.equal(state.visible, false);
  assert.equal(state.gap, "2");
});

test("a visible display value hydrates visible true", () => {
  const state = hydrateInspectorState(node("fgrid"), "flex");
  assert.equal(state.visible, true);
});

// ── empty ───────────────────────────────────────────────────────────────────

test("no facets, no props → an empty partial (defaults stand)", () => {
  const state = hydrateInspectorState(node("root"), "");
  assert.deepEqual(state, {});
});

// ── W3.2 §2 additions: text style (ruling 25) and line spacing (ruling 26) ──

test("text: the variant hydrates the style select; line spacing from leading-", () => {
  const withLeading = hydrateInspectorState(
    node("sub"),
    "text-lg leading-relaxed",
  );
  assert.equal(withLeading.lineSpacing, "relaxed");
  // Harvested text nodes carry variant "body" (the engine default).
  const state = hydrate("sub");
  assert.equal(state.textStyle, "Body");
});

test("text: a non-default variant maps to its select label", () => {
  const h2 = { ...node("headline"), variant: "h2" };
  const state = hydrateInspectorState(h2, h2.classes);
  assert.equal(state.textStyle, "H2");
});

test("non-text nodes hydrate no style; absent leading omits line spacing", () => {
  const state = hydrate("cta");
  assert.ok(!("textStyle" in state));
  assert.ok(!("lineSpacing" in state));
});

// ── W4.5: the canvas schema's background (row 1) ────────────────────────────

test("row 1: the page root's bg token reaches the canvas schema's state", () => {
  const root = HARVESTED_PAGE_ROOT_V47.nodes.root;
  assert.ok(root);
  // The canvas schema is chosen by ID, not kind (the root is a container).
  assert.deepEqual(
    inspectorSelectionFor(root, HARVESTED_PAGE_ROOT_V47.page_root),
    { selection: "canvas", layoutOnly: false },
  );
  // root: "bg-surface-canvas" — the document's own theme token, capitalized
  // into the label the picker options use.
  const state = hydrateInspectorState(root, root.classes);
  assert.equal(state.tokenBackgroundColor, "Surface-canvas");
});

test("row 1: a page root with no background token leaves the dummy default", () => {
  const root = HARVESTED_PAGE_ROOT_V47.nodes.root;
  assert.ok(root);
  const bare = hydrateInspectorState({ ...root, classes: "" }, "");
  assert.ok(!("tokenBackgroundColor" in bare));
});

// ══ W4.9 — the eye and the segmented are ONE facet (rows 40 × 20) ═══════════

test("row 40 × 20: the container the eye hid hydrates BOTH invisible and Hide", () => {
  // Real bytes, written by the eye itself on the live editor (v51 → v52).
  const fgrid = HARVESTED_HIDDEN_CONTAINER_V52.nodes.fgrid;
  assert.ok(fgrid, "harvested hidden container missing");
  assert.equal(fgrid.kind, "container");
  const state = hydrateInspectorState(fgrid, fgrid.classes);
  // One display parse feeds both controls, so they cannot disagree.
  assert.equal(state.visible, false);
  assert.equal(state.layoutMode, "Hide");
  // And the eye's write displaced ONLY the display family.
  assert.deepEqual(state.padding, { bottom: "8", left: "4", right: "4", top: "8" });
  assert.equal(state.gap, "6");
  assert.equal(state.tokenBackgroundColor, "Card");
  assert.equal(state.tokenTextColor, "Dark");
});
