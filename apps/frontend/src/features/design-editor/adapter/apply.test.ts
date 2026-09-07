import assert from "node:assert/strict";
import test from "node:test";
import type { WebNode } from "../engine/webDocuments";
import {
  HARVESTED_ICON_V56,
  HARVESTED_IMAGE_PAGE,
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

// W4.2 (lane B): the image/radius harvest is a second real document
// (img_plain "object-contain rounded-[8px] w-80", img_linked "object-cover
// rounded-lg rounded-tl-[4px] w-80" + href/new_tab, img_bare "rounded w-80",
// cta a link-form secondary button).
function imageNode(id: string): WebNode {
  const found = HARVESTED_IMAGE_PAGE.nodes[id];
  assert.ok(found, `image fixture node ${id} missing`);
  return found;
}

function changeOn(
  node: WebNode,
  property: string,
  value: unknown,
): ReturnType<typeof inspectorChangeToOperation> {
  return inspectorChangeToOperation(
    { property, selectionId: node.id, value },
    node,
    PAGE_ID,
  );
}

function changeImage(
  property: string,
  value: unknown,
  nodeId: string,
): ReturnType<typeof inspectorChangeToOperation> {
  return changeOn(imageNode(nodeId), property, value);
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
  assert.equal(change("textColor", "#123456"), null);
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

// ── image fill mode (row 13) ────────────────────────────────────────────────

test("fillMode maps each kept label onto the objectFit facet", () => {
  // img_plain: "object-contain rounded-[8px] w-80" — the facet rewrites only
  // the object-fit token, every other token survives verbatim and in order.
  assert.deepEqual(changeImage("fillMode", "Fit", "img_plain"), {
    classes: "rounded-[8px] w-80 object-contain",
    id: "img_plain",
    kind: "set_node_classes",
    page_id: PAGE_ID,
  });
  const fill = changeImage("fillMode", "Fill", "img_plain");
  assert.ok(fill && fill.kind === "set_node_classes");
  assert.equal(fill.classes, "rounded-[8px] w-80 object-cover");
  const stretch = changeImage("fillMode", "Stretch", "img_plain");
  assert.ok(stretch && stretch.kind === "set_node_classes");
  assert.equal(stretch.classes, "rounded-[8px] w-80 object-fill");
});

test("Tile produces no operation (row 13: dropped from the options)", () => {
  assert.equal(changeImage("fillMode", "Tile", "img_plain"), null);
  assert.equal(changeImage("fillMode", "Contain", "img_plain"), null);
});

test("fillMode on a non-image node produces no operation", () => {
  assert.equal(changeImage("fillMode", "Fill", "cta"), null);
});

// ── link fields (rows 11/15, ruling R-B4) ──────────────────────────────────

test("an image url edit resends the FULL image props, asset_id/alt intact", () => {
  const op = changeImage("url", "https://example.com/next", "img_linked");
  assert.deepEqual(op, {
    id: "img_linked",
    kind: "set_node_props",
    page_id: PAGE_ID,
    props: {
      alt: "Teal banner",
      asset_id: "asset_c42b6ba24117",
      href: "https://example.com/next",
      kind: "image",
      new_tab: true,
    },
  });
});

test("an empty/whitespace image url commits href null (honest clear)", () => {
  for (const typed of ["", "   "]) {
    const op = changeImage("url", typed, "img_linked");
    assert.ok(op && op.kind === "set_node_props");
    assert.deepEqual(op.props, {
      alt: "Teal banner",
      asset_id: "asset_c42b6ba24117",
      href: null,
      kind: "image",
      new_tab: true,
    });
  }
});

test("openInNewTab is a BOOLEAN change and preserves the current href", () => {
  const off = changeImage("openInNewTab", false, "img_linked");
  assert.ok(off && off.kind === "set_node_props");
  assert.deepEqual(off.props, {
    alt: "Teal banner",
    asset_id: "asset_c42b6ba24117",
    href: "https://example.com/teal",
    kind: "image",
    new_tab: false,
  });
  // img_plain carries no href: the checkbox must not invent one.
  const unlinked = changeImage("openInNewTab", true, "img_plain");
  assert.ok(unlinked && unlinked.kind === "set_node_props");
  assert.deepEqual(unlinked.props, {
    alt: "Teal banner plain",
    asset_id: "asset_c42b6ba24117",
    href: null,
    kind: "image",
    new_tab: true,
  });
});

test("a non-boolean openInNewTab / non-string url produces no operation", () => {
  assert.equal(changeImage("openInNewTab", "true", "img_linked"), null);
  assert.equal(changeImage("url", true, "img_linked"), null);
});

test("a link-form button rebuilds its props, label + variant preserved", () => {
  // cta: secondary "See the offer", href https://example.com/offer.
  const op = changeImage("url", "https://example.com/pricing", "cta");
  assert.deepEqual(op, {
    id: "cta",
    kind: "set_node_props",
    page_id: PAGE_ID,
    props: {
      href: "https://example.com/pricing",
      kind: "button",
      label: "See the offer",
      new_tab: false,
      variant: "secondary",
    },
  });
  const newTab = changeImage("openInNewTab", true, "cta");
  assert.ok(newTab && newTab.kind === "set_node_props");
  assert.deepEqual(newTab.props, {
    href: "https://example.com/offer",
    kind: "button",
    label: "See the offer",
    new_tab: true,
    variant: "secondary",
  });
});

test("a command-form button gets NO write from either link field (row 36)", () => {
  // §4/row 36: dialog actions are agent-only; row 15: the inspector edits link
  // mode only — a command button's props must never be rewritten from here.
  const invoker: WebNode = {
    ...imageNode("cta"),
    command: "show_modal",
    command_target: "dlg_pricing",
  };
  assert.equal(changeOn(invoker, "url", "https://example.com/x"), null);
  assert.equal(changeOn(invoker, "openInNewTab", true), null);
});

test("link fields on any other kind produce no operation", () => {
  assert.equal(changeImage("url", "https://example.com", "hero"), null);
  // Container href exists engine-side but has no ruled UI — out of scope.
  assert.equal(changeImage("openInNewTab", true, "root"), null);
  assert.equal(change("url", "https://example.com", "sub"), null);
});

test("an image with no asset_id is refused rather than clobbered", () => {
  const broken: WebNode = { ...imageNode("img_linked"), asset_id: undefined };
  assert.equal(changeOn(broken, "url", "https://example.com"), null);
});

// ── radius (row 14 + founder ruling F2, ruling R-B1) ───────────────────────

test("radius.all with a numeric value CLEARS the corner overrides (F2)", () => {
  // img_linked: "object-cover rounded-lg rounded-tl-[4px] w-80" — one op:
  // four corner clears chained onto the all-corners set. Every unrelated token
  // survives byte-exact and in order.
  assert.deepEqual(changeImage("radius.all", "12", "img_linked"), {
    classes: "object-cover w-80 rounded-[12px]",
    id: "img_linked",
    kind: "set_node_classes",
    page_id: PAGE_ID,
  });
});

test("the all-corners write replaces the bare `rounded` default too", () => {
  // img_bare: "rounded w-80" — the engine owns the bare token for removal.
  const op = changeImage("radius.all", "8", "img_bare");
  assert.ok(op && op.kind === "set_node_classes");
  assert.equal(op.classes, "w-80 rounded-[8px]");
});

test("an empty radius.all clears ONLY the all-corners family", () => {
  const op = changeImage("radius.all", "", "img_linked");
  assert.ok(op && op.kind === "set_node_classes");
  assert.equal(op.classes, "object-cover rounded-tl-[4px] w-80");
});

test("a per-corner write leaves the all-corners token untouched", () => {
  const op = changeImage("radius.topRight", "6", "img_linked");
  assert.ok(op && op.kind === "set_node_classes");
  assert.equal(op.classes, "object-cover rounded-lg rounded-tl-[4px] w-80 rounded-tr-[6px]");
  const cleared = changeImage("radius.topLeft", "", "img_linked");
  assert.ok(cleared && cleared.kind === "set_node_classes");
  assert.equal(cleared.classes, "object-cover rounded-lg w-80");
});

test("a non-numeric radius value produces no operation (R-B1)", () => {
  // The field displays a named scale value verbatim ("lg"); committing it back
  // must not rewrite the class, and no unit/decimal/negative form is accepted.
  for (const typed of ["lg", "full", "8px", "[8px]", "4.5", "-4", "abc"]) {
    assert.equal(changeImage("radius.all", typed, "img_linked"), null);
    assert.equal(changeImage("radius.bottomRight", typed, "img_linked"), null);
  }
});

test("an explicit 0 is the ONE way to author a zero radius", () => {
  const op = changeImage("radius.all", "0", "img_plain");
  assert.ok(op && op.kind === "set_node_classes");
  assert.equal(op.classes, "object-contain w-80 rounded-[0px]");
});

test("radius writes apply to any node kind carrying the classes", () => {
  // cta (button): "bg-accent text-dark px-4 py-2 rounded-md".
  const op = changeImage("radius.bottomLeft", "2", "cta");
  assert.ok(op && op.kind === "set_node_classes");
  assert.equal(op.classes, "bg-accent text-dark px-4 py-2 rounded-md rounded-bl-[2px]");
});

// ── button style (row 16) ──────────────────────────────────────────────────

test("buttonLabel maps each kept label onto the engine variant", () => {
  // cta: link-form secondary "See the offer" @ https://example.com/offer —
  // the label/href/new_tab ride along byte-exact (set_node_props replaces the
  // props wholesale).
  assert.deepEqual(changeImage("buttonLabel", "Primary", "cta"), {
    id: "cta",
    kind: "set_node_props",
    page_id: PAGE_ID,
    props: {
      href: "https://example.com/offer",
      kind: "button",
      label: "See the offer",
      new_tab: false,
      variant: "primary",
    },
  });
  const secondary = changeImage("buttonLabel", "Secondary", "cta");
  assert.ok(secondary && secondary.kind === "set_node_props");
  assert.deepEqual(secondary.props, {
    href: "https://example.com/offer",
    kind: "button",
    label: "See the offer",
    new_tab: false,
    variant: "secondary",
  });
  const ghost = changeImage("buttonLabel", "Transparent", "cta");
  assert.ok(ghost && ghost.kind === "set_node_props");
  assert.deepEqual(ghost.props, {
    href: "https://example.com/offer",
    kind: "button",
    label: "See the offer",
    new_tab: false,
    variant: "ghost",
  });
});

test("Critical produces no operation (row 16: dropped from the options)", () => {
  // §2 delta: no engine `critical` variant, so the label — like any other
  // unmapped one — writes nothing rather than inventing a variant.
  assert.equal(changeImage("buttonLabel", "Critical", "cta"), null);
  assert.equal(changeImage("buttonLabel", "Outline", "cta"), null);
  assert.equal(changeImage("buttonLabel", "", "cta"), null);
});

test("a variant change on a COMMAND button preserves its command form", () => {
  const invoker: WebNode = {
    ...imageNode("cta"),
    command: "show_modal",
    command_target: "dlg_pricing",
    href: undefined,
  };
  const op = changeOn(invoker, "buttonLabel", "Primary");
  assert.ok(op && op.kind === "set_node_props");
  assert.deepEqual(op.props, {
    command: "show_modal",
    command_target: "dlg_pricing",
    kind: "button",
    label: "See the offer",
    variant: "primary",
  });
});

test("buttonLabel on a non-button node produces no operation", () => {
  assert.equal(changeImage("buttonLabel", "Primary", "img_plain"), null);
  assert.equal(change("buttonLabel", "Primary", "sub"), null);
});

// ── background color token (row 17, tokens only per R2) ────────────────────

test("tokenBackgroundColor writes the lowercased token through bgColor", () => {
  // cta: "bg-accent text-dark px-4 py-2 rounded-md" — only the bg- family is
  // rewritten; every unrelated token survives byte-exact and in order.
  const op = changeImage("tokenBackgroundColor", "Light", "cta");
  assert.ok(op && op.kind === "set_node_classes");
  assert.equal(op.classes, "text-dark px-4 py-2 rounded-md bg-light");
});

test("a hex background color produces no operation (tokens only, R2)", () => {
  assert.equal(changeImage("tokenBackgroundColor", "#123456", "cta"), null);
  assert.equal(changeImage("tokenBackgroundColor", "   ", "cta"), null);
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
  assert.equal(v33Change("tokenBackgroundColor", "#123456", "fgrid"), null);
  assert.equal(v33Change("backgroundColor", "#123456", "fgrid"), null);
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
  assert.equal(rootChange("tokenBackgroundColor", "#123456"), null);
  assert.equal(rootChange("backgroundColor", "#123456"), null);
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

// ══ W4.6 — the icon schema, trimmed to layout-only (ruling 18b) ═════════════
// The engine's icon node carries exactly one field — `icon`, the agent-authored
// name (`lumen-web`'s `WebNodeKind::Icon`) — and no icon facets exist, so the
// dummy's icon select / color tokens / size / stroke have NO backing. 18b hides
// those sections, leaving Layout/padding as the icon's one live surface. This
// block pins both halves: padding works on an icon, and nothing else does.

const V56_PAGE_ID = "home";

function iconChange(
  property: string,
  value: unknown,
): ReturnType<typeof inspectorChangeToOperation> {
  const node = HARVESTED_ICON_V56.nodes.ficon;
  assert.ok(node, "harvested icon missing");
  return inspectorChangeToOperation(
    { property, selectionId: node.id, value },
    node,
    V56_PAGE_ID,
  );
}

test("18b: the icon's padding X snaps to the nearest step and rewrites only that axis", () => {
  // ficon @56: "px-2 text-primary"
  const op = iconChange("padding.x", "7");
  assert.ok(op && op.kind === "set_node_classes");
  assert.equal(op.id, "ficon");
  assert.equal(op.page_id, V56_PAGE_ID);
  const tokens = op.classes.split(/\s+/);
  assert.ok(tokens.includes("px-6")); // 7 → nearest step 6
  assert.ok(!tokens.includes("px-2"));
  // The authored color token is not the icon schema's to touch (18b hides the
  // control) and survives verbatim.
  assert.ok(tokens.includes("text-primary"));
});

test("18b + R3: the icon's zero Y axis writes a real py utility", () => {
  // The two-box control shows Y as a truthful 0 (no py- utility at rest);
  // committing a value must ADD the axis, not rewrite px.
  const op = iconChange("padding.y", "7");
  assert.ok(op && op.kind === "set_node_classes");
  const tokens = op.classes.split(/\s+/);
  assert.ok(tokens.includes("py-6"));
  assert.ok(tokens.includes("px-2")); // the other axis is untouched
  assert.ok(tokens.includes("text-primary"));
});

test("18b: padding needs no icon-specific sanction — §5's layout-only kinds share it", () => {
  // Deliberately NOT an allowlist: §5 gives the same Layout(-padding) section
  // to embeds and every unmapped kind, so a kind guard on the padding cases
  // would break them. Icons are one member of that layout-only family, not an
  // exception to it.
  const embed = v33Change("padding.x", "4", "fembed");
  assert.ok(embed && embed.kind === "set_node_classes");
  assert.ok(embed.classes.split(/\s+/).includes("px-4"));
});

test("18b: every section the icon schema drops has no write behind it either", () => {
  // The hidden controls (icon select, icon color, size, stroke) and the Link-to
  // section the engine's icon node cannot back. Absent in the view AND refused
  // here, so a stray event can never write one.
  for (const [property, value] of [
    ["iconName", "Apple"],
    ["iconSize", "Large"],
    ["iconStroke", "Bold"],
    ["iconColor", "Content"],
    ["tokenBackgroundColor", "Primary"],
    ["url", "https://example.com"],
    ["openInNewTab", true],
    // Layout controls that belong to other schemas stay refused on an icon.
    ["layoutMode", "Grid"],
    ["direction", "horizontal"],
    ["gap", "4"],
    ["wrap", true],
  ] as ReadonlyArray<[string, unknown]>) {
    assert.equal(iconChange(property, value), null, `${property} must not write`);
  }
});

test("18b: an icon padding edit never rewrites the icon's props", () => {
  // `icon` (the agent-authored name) and `name` are props; the whole point of
  // 18b is that the inspector does not own them. The adapter is pure, so the
  // harvested node is byte-identical after the edits and no operation carries
  // props at all.
  const node = HARVESTED_ICON_V56.nodes.ficon;
  assert.ok(node);
  const before = JSON.stringify(node);
  for (const value of ["0", "6", "24"]) {
    const x = iconChange("padding.x", value);
    const y = iconChange("padding.y", value);
    assert.ok(x && x.kind === "set_node_classes");
    assert.ok(y && y.kind === "set_node_classes");
  }
  assert.equal(JSON.stringify(HARVESTED_ICON_V56.nodes.ficon), before);
  assert.equal(HARVESTED_ICON_V56.nodes.ficon.icon, "star");
});
