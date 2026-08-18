import assert from "node:assert/strict";
import test from "node:test";
import { HARVESTED_PAGE, HARVESTED_PAGE_V33 } from "./__fixtures__/web-nodes";
import { inspectorChangeToOperation } from "./apply";

// W3.2: inspector change events → engine operations, one test per control.
// Fixtures are the real harvested nodes; `sub` is the canonical text node
// ("text-lg text-slate-300 text-center max-w-xl").

const PAGE_ID = "home";

function change(
  property: string,
  value: unknown,
  nodeId = "sub",
): ReturnType<typeof inspectorChangeToOperation> {
  const node = HARVESTED_PAGE.nodes[nodeId];
  assert.ok(node);
  return inspectorChangeToOperation(
    { property, selectionId: nodeId, value },
    node,
    PAGE_ID,
  );
}

// ── size (row 5) ────────────────────────────────────────────────────────────

test("fontSize maps the label back onto the ramp and rewrites only textSize", () => {
  const op = change("fontSize", "24");
  assert.deepEqual(op, {
    classes: "text-slate-300 text-center max-w-xl text-2xl",
    id: "sub",
    kind: "set_node_classes",
    page_id: PAGE_ID,
  });
});

test("a fontSize outside the contract ramp produces no operation", () => {
  assert.equal(change("fontSize", "13"), null);
  assert.equal(change("fontSize", "64"), null);
});

// ── weight (row 6) ──────────────────────────────────────────────────────────

test("fontWeight maps the select label to the facet token", () => {
  const op = change("fontWeight", "Semi Bold");
  assert.ok(op && op.kind === "set_node_classes");
  assert.ok(op.classes.includes("font-semibold"));
  // The other tokens are untouched.
  assert.ok(op.classes.includes("text-lg"));
  assert.ok(op.classes.includes("text-center"));
});

// ── color token (row 4, tokens only per R2) ────────────────────────────────

test("tokenTextColor writes the lowercased token through the textColor facet", () => {
  const op = change("tokenTextColor", "Dark");
  assert.ok(op && op.kind === "set_node_classes");
  assert.ok(op.classes.includes("text-dark"));
  assert.ok(!op.classes.includes("text-slate-300"));
  // Size survives the color rewrite (they share the text- prefix).
  assert.ok(op.classes.includes("text-lg"));
});

test("a raw hex color produces no operation (custom tab is inert, §3)", () => {
  assert.equal(change("textColor", "#00F59B"), null);
});

// ── alignment (row 7) ───────────────────────────────────────────────────────

test("horizontalAlignment maps onto the textAlign facet", () => {
  const op = change("horizontalAlignment", "right");
  assert.ok(op && op.kind === "set_node_classes");
  assert.ok(op.classes.includes("text-right"));
  assert.ok(!op.classes.includes("text-center"));
});

// ── padding (R3: two axis boxes, nearest spacing step) ─────────────────────

test("padding.x snaps to the nearest spacing step and rewrites paddingX", () => {
  const op = change("padding.x", "7");
  assert.ok(op && op.kind === "set_node_classes");
  assert.ok(op.classes.includes("px-6")); // 7 → nearest step 6
});

test("padding.y accepts an exact step", () => {
  const op = change("padding.y", "12");
  assert.ok(op && op.kind === "set_node_classes");
  assert.ok(op.classes.includes("py-12"));
});

test("a non-numeric padding value produces no operation", () => {
  assert.equal(change("padding.x", "lots"), null);
});

// ── text style variant (ruling 25) ─────────────────────────────────────────

test("textStyle maps the label to the engine variant and resends content", () => {
  const node = HARVESTED_PAGE.nodes.sub;
  const op = change("textStyle", "H2");
  assert.deepEqual(op, {
    id: "sub",
    kind: "set_node_props",
    page_id: PAGE_ID,
    props: { content: node.content, kind: "text", variant: "h2" },
  });
});

test("textStyle on a non-text node produces no operation", () => {
  assert.equal(change("textStyle", "H2", "cta"), null);
});

// ── line spacing (ruling 26) ────────────────────────────────────────────────

test("lineSpacing writes the lineHeight facet", () => {
  const op = change("lineSpacing", "relaxed");
  assert.ok(op && op.kind === "set_node_classes");
  assert.ok(op.classes.includes("leading-relaxed"));
});

// ── refusals ────────────────────────────────────────────────────────────────

test("an unmapped property produces no operation", () => {
  assert.equal(change("strokeWidth", "2"), null);
  assert.equal(change("fontFamily", "Inter"), null); // R1: theme owns fonts
});

// ══ W4.4 — container & section schemas (rows 19/20/22, §4) ══════════════════
// Fixtures are the v33 harvest, whose hero section carries BOTH section props
// (`tag` + `anchor_id`) — the real bytes the §4 guarantee is proven against.

const V33_PAGE_ID = "home";

function v33Change(
  property: string,
  value: unknown,
  nodeId: string,
): ReturnType<typeof inspectorChangeToOperation> {
  const node = HARVESTED_PAGE_V33.nodes[nodeId];
  assert.ok(node, `fixture node ${nodeId} missing`);
  return inspectorChangeToOperation(
    { property, selectionId: nodeId, value },
    node,
    V33_PAGE_ID,
  );
}

// ── style tokens (row 19; the row-17 popover pattern) ──────────────────────

test("container tokenBackgroundColor writes the lowercased token through bgColor", () => {
  // fgrid: "grid grid-cols-3 gap-6 px-4 py-2 bg-card text-dark"
  const op = v33Change("tokenBackgroundColor", "Dark", "fgrid");
  assert.ok(op && op.kind === "set_node_classes");
  assert.ok(op.classes.includes("bg-dark"));
  assert.ok(!op.classes.includes("bg-card"));
  // Every other family survives verbatim.
  assert.ok(op.classes.includes("grid-cols-3"));
  assert.ok(op.classes.includes("gap-6"));
  assert.ok(op.classes.includes("text-dark"));
});

test("container tokenTextColor writes textColor and leaves the background", () => {
  const op = v33Change("tokenTextColor", "Muted", "fgrid");
  assert.ok(op && op.kind === "set_node_classes");
  assert.ok(op.classes.includes("text-muted"));
  assert.ok(!op.classes.includes("text-dark"));
  assert.ok(op.classes.includes("bg-card"));
});

test("section style tokens write both color facets", () => {
  // hero: "flex flex-col items-center gap-6 py-24 px-8 bg-slate-900"
  const background = v33Change("tokenBackgroundColor", "Light", "hero");
  assert.ok(background && background.kind === "set_node_classes");
  assert.ok(background.classes.includes("bg-light"));
  assert.ok(!background.classes.includes("bg-slate-900"));
  const text = v33Change("tokenTextColor", "Primary", "hero");
  assert.ok(text && text.kind === "set_node_classes");
  assert.ok(text.classes.includes("text-primary"));
});

test("a background token on a kind with no sanctioned background control is refused", () => {
  // Row 19 sanctions container/section (row 1 the page root, itself a
  // container); a text/icon/embed node has no background control in v1.
  assert.equal(v33Change("tokenBackgroundColor", "Dark", "sub"), null);
  assert.equal(v33Change("tokenBackgroundColor", "Dark", "ficon"), null);
  assert.equal(v33Change("tokenBackgroundColor", "Dark", "fembed"), null);
});

test("a hex background (the §3-inert custom tab) produces no operation", () => {
  assert.equal(v33Change("tokenBackgroundColor", "#00F59B", "fgrid"), null);
  assert.equal(v33Change("backgroundColor", "#00F59B", "fgrid"), null);
});

// ── §4: the props-preservation guarantee (item 38) ─────────────────────────

/** Every container/section style control this task wires. The §4 test runs the
 * whole battery, so a future style control added here without a
 * `set_node_classes` mapping fails loudly. */
const SECTION_STYLE_EDITS: ReadonlyArray<[string, unknown]> = [
  ["tokenTextColor", "Primary"],
  ["tokenBackgroundColor", "Light"],
  ["padding.x", "6"],
  ["padding.y", "10"],
];

test("§4: a style edit on a section is a set_node_classes operation, never set_node_props", () => {
  for (const [property, value] of SECTION_STYLE_EDITS) {
    const op = v33Change(property, value, "hero");
    assert.ok(op, `${property} produced no operation`);
    assert.equal(
      op.kind,
      "set_node_classes",
      `${property} must not rewrite the section's props`,
    );
  }
});

test("§4: the section's tag/anchor_id round-trip byte-identically through every style edit", () => {
  const hero = HARVESTED_PAGE_V33.nodes.hero;
  assert.ok(hero);
  // The harvested bytes, before anything runs.
  assert.equal(hero.tag, "section");
  assert.equal(hero.anchor_id, "hero-anchor");
  const before = JSON.stringify(hero);
  for (const [property, value] of SECTION_STYLE_EDITS) {
    v33Change(property, value, "hero");
  }
  // The adapter is pure: it never mutates the node it is handed, and no
  // operation it emits carries props at all.
  assert.equal(JSON.stringify(HARVESTED_PAGE_V33.nodes.hero), before);
  assert.equal(HARVESTED_PAGE_V33.nodes.hero.tag, "section");
  assert.equal(HARVESTED_PAGE_V33.nodes.hero.anchor_id, "hero-anchor");
});
