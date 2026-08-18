import assert from "node:assert/strict";
import test from "node:test";
import type { WebNode } from "../engine/webDocuments";
import { HARVESTED_IMAGE_PAGE, HARVESTED_PAGE } from "./__fixtures__/web-nodes";
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

// ── refusals ────────────────────────────────────────────────────────────────

test("an unmapped property produces no operation", () => {
  assert.equal(change("strokeWidth", "2"), null);
  assert.equal(change("fontFamily", "Inter"), null); // R1: theme owns fonts
});
