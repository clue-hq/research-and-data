import assert from "node:assert/strict";
import test from "node:test";
import {
  HARVESTED_PAGE,
  HARVESTED_PAGE_ROOT_V47,
  HARVESTED_PAGE_V33,
} from "./__fixtures__/web-nodes";
import { inspectorChangeToOperation, nextVisibilityMemory } from "./apply";

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

// ── container display segmented (row 20) ───────────────────────────────────

test("layoutMode maps the segmented labels onto the display facet", () => {
  const grid = v33Change("layoutMode", "Grid", "fgrid");
  assert.ok(grid && grid.kind === "set_node_classes");
  assert.ok(grid.classes.split(/\s+/).includes("grid"));
  const flex = v33Change("layoutMode", "Flex", "fgrid");
  assert.ok(flex && flex.kind === "set_node_classes");
  assert.ok(flex.classes.split(/\s+/).includes("flex"));
  assert.ok(!flex.classes.split(/\s+/).includes("grid"));
  // The column count and every other family survive the display rewrite.
  assert.ok(flex.classes.includes("grid-cols-3"));
});

test("layoutMode Hide writes the display facet's hidden value (row 40 shares it)", () => {
  const op = v33Change("layoutMode", "Hide", "fgrid");
  assert.ok(op && op.kind === "set_node_classes");
  assert.ok(op.classes.split(/\s+/).includes("hidden"));
});

test("layoutMode outside the segmented vocabulary, or on a section, is refused", () => {
  // block/inline-flex have no dummy slot (§6(5) omission, row 20).
  assert.equal(v33Change("layoutMode", "block", "fgrid"), null);
  // The section schema ships no Flex/Grid/Hide segmented control.
  assert.equal(v33Change("layoutMode", "Grid", "hero"), null);
});

// ── section direction / gap / wrap (row 22) ────────────────────────────────

test("direction maps the segmented value onto the flex-direction facet", () => {
  // hero: "flex flex-col items-center gap-6 py-24 px-8 …"
  const horizontal = v33Change("direction", "horizontal", "hero");
  assert.ok(horizontal && horizontal.kind === "set_node_classes");
  assert.ok(horizontal.classes.split(/\s+/).includes("flex-row"));
  assert.ok(!horizontal.classes.split(/\s+/).includes("flex-col"));
  // The `flex` display utility is a different family and survives.
  assert.ok(horizontal.classes.split(/\s+/).includes("flex"));
  const vertical = v33Change("direction", "vertical", "hero");
  assert.ok(vertical && vertical.kind === "set_node_classes");
  assert.ok(vertical.classes.split(/\s+/).includes("flex-col"));
});

test("gap snaps a typed value to the nearest enumerated step", () => {
  const op = v33Change("gap", "7", "hero");
  assert.ok(op && op.kind === "set_node_classes");
  assert.ok(op.classes.split(/\s+/).includes("gap-6")); // 7 → nearest step 6
  const exact = v33Change("gap", "12", "hero");
  assert.ok(exact && exact.kind === "set_node_classes");
  assert.ok(exact.classes.split(/\s+/).includes("gap-12"));
  const above = v33Change("gap", "99", "hero");
  assert.ok(above && above.kind === "set_node_classes");
  assert.ok(above.classes.split(/\s+/).includes("gap-24")); // clamped to the top step
});

test("a non-numeric gap produces no operation", () => {
  assert.equal(v33Change("gap", "wide", "hero"), null);
});

test("wrap maps the boolean onto the flex-wrap facet", () => {
  const on = v33Change("wrap", true, "hero");
  assert.ok(on && on.kind === "set_node_classes");
  assert.ok(on.classes.split(/\s+/).includes("flex-wrap"));
  const off = v33Change("wrap", false, "hero");
  assert.ok(off && off.kind === "set_node_classes");
  assert.ok(off.classes.split(/\s+/).includes("flex-nowrap"));
  assert.ok(!off.classes.split(/\s+/).includes("flex-wrap"));
  // flex-direction is its own family (`flex-col` survives a wrap write).
  assert.ok(off.classes.split(/\s+/).includes("flex-col"));
});

test("direction/gap/wrap on a container are refused (row 21 is future work)", () => {
  // The dummy gives these three to the SECTION schema only; container-level
  // direction/gap/wrap is §7 item 1, with no UI slot decided.
  assert.equal(v33Change("direction", "horizontal", "fgrid"), null);
  assert.equal(v33Change("gap", "4", "fgrid"), null);
  assert.equal(v33Change("wrap", true, "fgrid"), null);
});

// ── §4: the props-preservation guarantee (item 38) ─────────────────────────

/** Every container/section style control this task wires. The §4 test runs the
 * whole battery, so a future style control added here without a
 * `set_node_classes` mapping fails loudly. */
const SECTION_STYLE_EDITS: ReadonlyArray<[string, unknown]> = [
  ["tokenTextColor", "Primary"],
  ["tokenBackgroundColor", "Light"],
  ["direction", "horizontal"],
  ["gap", "8"],
  ["wrap", true],
  ["wrap", false],
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

// ══ W4.5 — the canvas schema (the page ROOT) ════════════════════════════════
// Contract row 1: the canvas Background is the page background. The canvas
// selection is chosen by node ID (`inspectorSelectionFor` returns "canvas" for
// `page.root`), never by kind, and `lumen-web` builds every page root as a
// Container — so row 1's write rides row 19's kind set instead of naming a
// root kind that does not exist. The fixture below pins that dependency.

const V47_PAGE_ID = "home";

function rootChange(
  property: string,
  value: unknown,
): ReturnType<typeof inspectorChangeToOperation> {
  const node = HARVESTED_PAGE_ROOT_V47.nodes.root;
  assert.ok(node, "harvested page root missing");
  return inspectorChangeToOperation(
    { property, selectionId: node.id, value },
    node,
    V47_PAGE_ID,
  );
}

test("row 1: the harvested page root is a container, so the background-token kind set covers it", () => {
  const root = HARVESTED_PAGE_ROOT_V47.nodes.root;
  assert.ok(root);
  assert.equal(root.id, HARVESTED_PAGE_ROOT_V47.page_root);
  assert.equal(root.kind, "container");
});

test("row 1: a canvas background token writes bg-<token> onto the root node", () => {
  // root: "bg-surface-canvas"
  const op = rootChange("tokenBackgroundColor", "Surface-card");
  assert.ok(op && op.kind === "set_node_classes");
  assert.equal(op.id, "root");
  assert.equal(op.page_id, V47_PAGE_ID);
  assert.ok(op.classes.split(/\s+/).includes("bg-surface-card"));
  assert.ok(!op.classes.includes("bg-surface-canvas"));
});

test("row 1: the canvas background rewrites only its own family", () => {
  const node = HARVESTED_PAGE_ROOT_V47.nodes.root;
  assert.ok(node);
  const op = inspectorChangeToOperation(
    { property: "tokenBackgroundColor", selectionId: "root", value: "Dark" },
    { ...node, classes: "flex flex-col bg-surface-canvas text-primary" },
    V47_PAGE_ID,
  );
  assert.ok(op && op.kind === "set_node_classes");
  const tokens = op.classes.split(/\s+/);
  assert.ok(tokens.includes("bg-dark"));
  assert.ok(tokens.includes("flex"));
  assert.ok(tokens.includes("flex-col"));
  assert.ok(tokens.includes("text-primary"));
});

test("row 1: the canvas hex/custom tab stays §3-inert", () => {
  assert.equal(rootChange("tokenBackgroundColor", "#00F59B"), null);
  assert.equal(rootChange("backgroundColor", "#00F59B"), null);
});

test("row 1: kinds with no background control are still refused (embed/icon)", () => {
  // The canvas wiring widens no guard: a node the schema map never sends to
  // the canvas keeps its refusal.
  assert.equal(v33Change("tokenBackgroundColor", "Surface-card", "fembed"), null);
  assert.equal(v33Change("tokenBackgroundColor", "Surface-card", "ficon"), null);
});

// ══ W4.9 — the header visibility eye (row 40) ═══════════════════════════════
// The eye writes the SAME display facet W4.4's container segmented writes, so
// the two controls compose. Un-hiding restores only a display value the
// session actually observed at hide time; with nothing captured it clears the
// token and lets the page's natural display stand — it never guesses.

function visibilityChange(
  nodeId: string,
  visible: boolean,
  restoreDisplay?: string | null,
  classesOverride?: string,
): ReturnType<typeof inspectorChangeToOperation> {
  const node = HARVESTED_PAGE_V33.nodes[nodeId];
  assert.ok(node, `fixture node ${nodeId} missing`);
  return inspectorChangeToOperation(
    { property: "visible", restoreDisplay, selectionId: nodeId, value: visible },
    classesOverride === undefined ? node : { ...node, classes: classesOverride },
    V33_PAGE_ID,
  );
}

test("row 40: hiding writes the display facet's hidden, preserving every other token", () => {
  // fgrid: "grid grid-cols-3 gap-6 px-4 py-2 bg-card text-dark"
  const op = visibilityChange("fgrid", false);
  assert.ok(op && op.kind === "set_node_classes");
  assert.equal(op.id, "fgrid");
  assert.equal(op.page_id, V33_PAGE_ID);
  const tokens = op.classes.split(/\s+/);
  assert.ok(tokens.includes("hidden"));
  assert.ok(!tokens.includes("grid"));
  assert.deepEqual(tokens.filter((token) => token !== "hidden"), [
    "grid-cols-3",
    "gap-6",
    "px-4",
    "py-2",
    "bg-card",
    "text-dark",
  ]);
});

test("row 40: the eye serves every schema kind, not just the layout ones", () => {
  for (const nodeId of ["headline", "fimg", "cta", "ficon", "fgrid", "hero"]) {
    const op = visibilityChange(nodeId, false);
    assert.ok(op && op.kind === "set_node_classes", `${nodeId} produced no operation`);
    assert.ok(op.classes.split(/\s+/).includes("hidden"), nodeId);
  }
});

test("row 40: un-hiding restores exactly the display the session captured", () => {
  const op = visibilityChange("fgrid", true, "grid", "hidden grid-cols-3 gap-6 bg-card");
  assert.ok(op && op.kind === "set_node_classes");
  const tokens = op.classes.split(/\s+/);
  assert.ok(tokens.includes("grid"));
  assert.ok(!tokens.includes("hidden"));
  assert.deepEqual(tokens, ["grid-cols-3", "gap-6", "bg-card", "grid"]);
});

test("row 40: un-hiding with nothing captured clears the display token rather than guessing", () => {
  const op = visibilityChange("fgrid", true, null, "hidden grid-cols-3 gap-6 bg-card");
  assert.ok(op && op.kind === "set_node_classes");
  assert.deepEqual(op.classes.split(/\s+/), ["grid-cols-3", "gap-6", "bg-card"]);
  // The absent-capture case (no `restoreDisplay` key at all) is the same.
  const undefinedCapture = visibilityChange("fgrid", true, undefined, "hidden gap-6");
  assert.ok(undefinedCapture && undefinedCapture.kind === "set_node_classes");
  assert.deepEqual(undefinedCapture.classes.split(/\s+/), ["gap-6"]);
});

test("row 40: a non-boolean visible value is refused", () => {
  assert.equal(visibilityChange("fgrid", "true" as unknown as boolean), null);
  assert.equal(visibilityChange("fgrid", null as unknown as boolean), null);
});

test("row 40: the eye never rewrites props (the §4 guarantee holds for it too)", () => {
  const hero = HARVESTED_PAGE_V33.nodes.hero;
  assert.ok(hero);
  const before = JSON.stringify(hero);
  const hide = visibilityChange("hero", false);
  const show = visibilityChange("hero", true, "flex");
  assert.ok(hide && hide.kind === "set_node_classes");
  assert.ok(show && show.kind === "set_node_classes");
  assert.equal(JSON.stringify(HARVESTED_PAGE_V33.nodes.hero), before);
});

// ── the pre-hide capture (the eye's per-selection memory) ───────────────────

test("row 40: hiding captures the node's real display value for the un-hide", () => {
  const fgrid = HARVESTED_PAGE_V33.nodes.fgrid;
  assert.ok(fgrid);
  const next = nextVisibilityMemory(null, fgrid, false);
  assert.deepEqual(next.memory, { display: "grid", nodeId: "fgrid" });
  assert.equal(next.restoreDisplay, null);
});

test("row 40: a node with no display utility captures nothing (un-hide clears)", () => {
  const cta = HARVESTED_PAGE_V33.nodes.cta;
  assert.ok(cta);
  // cta carries no display token at all.
  const next = nextVisibilityMemory(null, cta, false);
  assert.equal(next.memory, null);
  assert.equal(nextVisibilityMemory(next.memory, cta, true).restoreDisplay, null);
});

test("row 40: a node already hidden at selection time captures nothing", () => {
  const fgrid = HARVESTED_PAGE_V33.nodes.fgrid;
  assert.ok(fgrid);
  const next = nextVisibilityMemory(null, { ...fgrid, classes: "hidden gap-6" }, false);
  assert.equal(next.memory, null);
});

test("row 40: the capture is consumed once and never crosses to another node", () => {
  const fgrid = HARVESTED_PAGE_V33.nodes.fgrid;
  const hero = HARVESTED_PAGE_V33.nodes.hero;
  assert.ok(fgrid && hero);
  const captured = nextVisibilityMemory(null, fgrid, false).memory;
  assert.deepEqual(captured, { display: "grid", nodeId: "fgrid" });
  // Another node's un-hide must not inherit fgrid's display.
  assert.equal(nextVisibilityMemory(captured, hero, true).restoreDisplay, null);
  // The owner's un-hide restores it, and clears the memory behind it.
  const restored = nextVisibilityMemory(captured, fgrid, true);
  assert.equal(restored.restoreDisplay, "grid");
  assert.equal(restored.memory, null);
  assert.equal(nextVisibilityMemory(restored.memory, fgrid, true).restoreDisplay, null);
});
