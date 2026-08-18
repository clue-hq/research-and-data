import assert from "node:assert/strict";
import test from "node:test";
import type { WebNode } from "../engine/webDocuments";
import {
  HARVESTED_IMAGE_PAGE,
  HARVESTED_PAGE,
  IMAGE_RADIUS_CLASS_VARIANTS,
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

// W4.2 (lane B): the image/radius harvest is a second real document.
function imageNode(id: string): WebNode {
  const found = HARVESTED_IMAGE_PAGE.nodes[id];
  assert.ok(found, `image fixture node ${id} missing`);
  return found;
}

function hydrateImage(id: string) {
  const n = imageNode(id);
  return hydrateInspectorState(n, n.classes);
}

/** §1 row 14: an absent facet is the designed empty — NEVER "0". */
const EMPTY_RADIUS = {
  all: "",
  bottomLeft: "",
  bottomRight: "",
  topLeft: "",
  topRight: "",
};

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

test("section: direction/gap hydrate per §1 row 22; absent wrap is omitted", () => {
  // hero: "flex flex-col items-center gap-6 py-24 px-8 bg-slate-900"
  const state = hydrate("hero");
  assert.equal(state.direction, "vertical"); // col
  assert.equal(state.gap, "6");
  assert.equal(state.layoutMode, "Flex");
  assert.equal(state.tokenBackgroundColor, "Slate-900");
  assert.ok(!("wrap" in state)); // no flex-wrap token → dummy default stands
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

test("no facets, no props → only the always-on radius record (defaults stand)", () => {
  // §1 row 14 / ruling R-B1: radius is the one field that hydrates for EVERY
  // node — the dummy default lies about real nodes, so the full record must
  // always override it. Everything else stays omitted.
  const state = hydrateInspectorState(node("root"), "");
  assert.deepEqual(state, { radius: EMPTY_RADIUS });
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

// ── W4.2 (lane B): radius (§1 row 14, ruling R-B1) + the image harvest ──────

test("image: an arbitrary pixel radius displays as its bare number", () => {
  // img_plain: "object-contain rounded-[8px] w-80"
  const state = hydrateImage("img_plain");
  assert.deepEqual(state.radius, { ...EMPTY_RADIUS, all: "8" });
});

test("image: a named all-corners radius plus a corner override", () => {
  // img_linked: "object-cover rounded-lg rounded-tl-[4px] w-80"
  const state = hydrateImage("img_linked");
  assert.deepEqual(state.radius, {
    ...EMPTY_RADIUS,
    all: "lg", // named scale values display verbatim
    topLeft: "4",
  });
});

test("bare `rounded` hydrates the empty radius, never zero", () => {
  // img_bare: "rounded w-80" — the engine owns the bare token for removal but
  // parses null, and null must never render as "0" (it would later write
  // rounded-[0px] from an untouched field).
  const state = hydrateImage("img_bare");
  assert.deepEqual(state.radius, EMPTY_RADIUS);
});

test("no radius utility at all hydrates the empty radius", () => {
  const state = hydrateInspectorState(
    imageNode("img_plain"),
    IMAGE_RADIUS_CLASS_VARIANTS.none,
  );
  assert.deepEqual(state.radius, EMPTY_RADIUS);
});

test("a variant-prefixed radius token is opaque and hydrates empty", () => {
  const state = hydrateInspectorState(
    imageNode("img_plain"),
    IMAGE_RADIUS_CLASS_VARIANTS.variantOnly,
  );
  assert.deepEqual(state.radius, EMPTY_RADIUS);
});

test("only the exact [Npx] shape unwraps; other arbitrary values are verbatim", () => {
  const percent = hydrateInspectorState(
    imageNode("img_plain"),
    IMAGE_RADIUS_CLASS_VARIANTS.arbitraryNonPixel,
  );
  assert.deepEqual(percent.radius, { ...EMPTY_RADIUS, all: "[50%]" });
  const named = hydrateInspectorState(
    imageNode("img_plain"),
    IMAGE_RADIUS_CLASS_VARIANTS.named,
  );
  assert.deepEqual(named.radius, { ...EMPTY_RADIUS, all: "full" });
});

test("radius hydrates for non-image nodes too (the button's rounded-md)", () => {
  // cta: "bg-accent text-dark px-4 py-2 rounded-md"
  const state = hydrateImage("cta");
  assert.deepEqual(state.radius, { ...EMPTY_RADIUS, all: "md" });
});

test("image: object-cover hydrates Fill; the linked pair hydrates (rows 11/13)", () => {
  const state = hydrateImage("img_linked");
  assert.equal(state.fillMode, "Fill"); // row 13, on a real image node
  assert.equal(state.url, "https://example.com/teal"); // row 11
  assert.equal(state.openInNewTab, true);
});

test("an unlinked image sets neither url nor openInNewTab", () => {
  // img_plain carries new_tab false but NO href — an absent link must leave
  // both fields untouched rather than hydrate a false/empty pair.
  const state = hydrateImage("img_plain");
  assert.ok(!("url" in state));
  assert.ok(!("openInNewTab" in state));
  assert.equal(state.fillMode, "Fit"); // object-contain → Fit
});
