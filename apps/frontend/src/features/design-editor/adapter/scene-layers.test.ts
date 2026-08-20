import assert from "node:assert/strict";
import test from "node:test";
import type { Node, Scene } from "../engine/scene/contracts";
import {
  AD_PAGE_ID,
  HARVESTED_AD_PAGE,
  adNode,
} from "./__fixtures__/scene-nodes";
import { rootFrameId, sceneSelectionFor } from "./scene-hydrate";
import { sceneLayerRows } from "./scene-layers";

/**
 * AD2.6 is proven against AD2.2's harvested bytes only (the W2.2 law). The
 * fixture tree is:
 *
 *   frame_ad_root                 (the artboard — routes to the canvas schema)
 *     auto_row_copy               (auto_layout)
 *       text_headline
 *       group_proof               (group)
 *         ellipse_proof_dot
 *         text_proof_stat
 *     rect_accent_bar             (rect, 3-stop linear gradient)
 *     line_divider                (§5 unrepresented kind)
 *     image_hero
 *
 * Three tests below need a shape the harvest does not contain (a nameless node,
 * a dangling child id, a cycle). Each DERIVES that shape from the harvested
 * bytes with one field changed and says so — no hand-written scenes.
 */

const ROOT = "frame_ad_root";
const ALL_EXPANDED = new Set([ROOT, "auto_row_copy", "group_proof"]);

function rowsWith(expanded: Iterable<string>) {
  return sceneLayerRows(HARVESTED_AD_PAGE, AD_PAGE_ID, new Set(expanded));
}

function derivedScene(nodes: Record<string, Node>): Scene {
  return {
    ...HARVESTED_AD_PAGE,
    nodes: { ...HARVESTED_AD_PAGE.nodes, ...nodes },
  };
}

test("the tree starts at the page's children, so the artboard is a depth-0 row", () => {
  const rows = rowsWith([]);
  assert.deepEqual(
    rows.map((row) => `${row.nodeId}@${row.depth}`),
    [`${ROOT}@0`],
  );
  // Collapsed, but the chevron is live: it has children to reveal.
  assert.equal(rows[0].expandable, true);
  assert.equal(rows[0].expanded, false);
});

test("expanding walks the real hierarchy in child order, at any depth", () => {
  assert.deepEqual(
    rowsWith(ALL_EXPANDED).map((row) => `${row.nodeId}@${row.depth}`),
    [
      `${ROOT}@0`,
      "auto_row_copy@1",
      "text_headline@2",
      "group_proof@2",
      "ellipse_proof_dot@3",
      "text_proof_stat@3",
      "rect_accent_bar@1",
      "line_divider@1",
      "image_hero@1",
    ],
  );
});

test("a collapsed container contributes its own row and nothing below it", () => {
  // The group is in the expansion set but its parent is not: nothing under
  // `auto_row_copy` may appear, the group row included.
  const rows = rowsWith([ROOT, "group_proof"]);
  assert.deepEqual(
    rows.map((row) => row.nodeId),
    [ROOT, "auto_row_copy", "rect_accent_bar", "line_divider", "image_hero"],
  );
  const autoRow = rows.find((row) => row.nodeId === "auto_row_copy");
  assert.equal(autoRow?.expandable, true);
  assert.equal(autoRow?.expanded, false);
});

test("a leaf is never expandable, even if the expansion set names it", () => {
  const rows = rowsWith([ROOT, "image_hero"]);
  const image = rows.find((row) => row.nodeId === "image_hero");
  assert.equal(image?.expandable, false);
  assert.equal(image?.expanded, false);
});

test("every kind takes its glyph from the dummy's own vocabulary", () => {
  const icons = new Map(
    rowsWith(ALL_EXPANDED).map((row) => [row.nodeId, row.icon]),
  );
  assert.deepEqual(Object.fromEntries(icons), {
    // frame and line have no glyph in the dummy set → the generic block glyph.
    [ROOT]: "div",
    auto_row_copy: "layout-template",
    ellipse_proof_dot: "ellipse",
    group_proof: "square-dashed",
    image_hero: "image",
    line_divider: "div",
    rect_accent_bar: "rectangle",
    text_headline: "type",
    text_proof_stat: "type",
  });
});

test("labels are the authored node names", () => {
  const labels = new Map(
    rowsWith(ALL_EXPANDED).map((row) => [row.nodeId, row.label]),
  );
  assert.deepEqual(Object.fromEntries(labels), {
    [ROOT]: "Ad artboard",
    auto_row_copy: "Copy row",
    ellipse_proof_dot: "Accent dot",
    group_proof: "Proof point",
    image_hero: "Hero image",
    line_divider: "Divider",
    rect_accent_bar: "Accent bar",
    text_headline: "Headline",
    text_proof_stat: "Proof stat",
  });
});

test("a nameless node falls back to the engine's own display name", () => {
  // DERIVED: every harvested node is named, but `Node.name` is `string | null`
  // in the contract and the API can serve null.
  const scene = derivedScene({ image_hero: { ...adNode("image_hero"), name: null } });
  const rows = sceneLayerRows(scene, AD_PAGE_ID, new Set([ROOT]));
  assert.equal(
    rows.find((row) => row.nodeId === "image_hero")?.label,
    "image image_hero",
  );
});

test("only a Rect/Ellipse solid fill produces the §1.7 fill chip", () => {
  const rows = rowsWith(ALL_EXPANDED);
  const swatch = (nodeId: string) =>
    rows.find((row) => row.nodeId === nodeId)?.fillSwatch;
  // The one solid-filled shape in the harvest.
  assert.equal(swatch("ellipse_proof_dot"), "#EA2261");
  // A gradient has no single hex. (UNCOVERED by the harvest: a SOLID rect —
  // the only rect in the real ad is the gradient accent bar. The rect and
  // ellipse take the identical path, proven on the ellipse.)
  assert.equal(swatch("rect_accent_bar"), undefined);
  // Solid fill, but not a shape kind: the chip is a Rect/Ellipse affordance.
  assert.equal(swatch("auto_row_copy"), undefined);
  assert.equal(swatch(ROOT), undefined);
  // A token fill cannot resolve to a hex without the brand kit.
  assert.equal(swatch("text_headline"), undefined);
});

test("selectable is AD2.4's oracle, not a second kind list", () => {
  const root = rootFrameId(HARVESTED_AD_PAGE, AD_PAGE_ID);
  for (const row of rowsWith(ALL_EXPANDED)) {
    assert.equal(
      row.selectable,
      sceneSelectionFor(adNode(row.nodeId), root) !== null,
      `${row.nodeId} disagrees with sceneSelectionFor`,
    );
  }
});

test("§5's unrepresented kind renders as a dead row, not a hidden one", () => {
  const line = rowsWith(ALL_EXPANDED).find((row) => row.nodeId === "line_divider");
  assert.ok(line, "the line is still a layer and still has a row");
  assert.equal(line.selectable, false);
  // Everything else in the harvest has a schema.
  assert.deepEqual(
    rowsWith(ALL_EXPANDED)
      .filter((row) => !row.selectable)
      .map((row) => row.nodeId),
    ["line_divider"],
  );
});

test("the artboard frame is selectable — it routes to the canvas schema", () => {
  assert.equal(rowsWith([])[0].selectable, true);
});

test("an unknown page has no rows", () => {
  assert.deepEqual(sceneLayerRows(HARVESTED_AD_PAGE, "page_missing", ALL_EXPANDED), []);
});

test("a child id the scene no longer carries is skipped, not thrown on", () => {
  // DERIVED: a rendered snapshot can lag the engine's scene by a frame.
  const scene = derivedScene({
    [ROOT]: {
      ...adNode(ROOT),
      children: ["auto_row_copy", "node_that_vanished", "image_hero"],
    },
  });
  assert.deepEqual(
    sceneLayerRows(scene, AD_PAGE_ID, new Set([ROOT])).map((row) => row.nodeId),
    [ROOT, "auto_row_copy", "image_hero"],
  );
});

test("a cyclic scene terminates instead of hanging the panel", () => {
  // DERIVED: malformed, but a malformed scene must not spin forever.
  const scene = derivedScene({
    image_hero: { ...adNode("image_hero"), children: [ROOT] },
  });
  const rows = sceneLayerRows(scene, AD_PAGE_ID, new Set([ROOT, "image_hero"]));
  assert.deepEqual(
    rows.map((row) => `${row.nodeId}@${row.depth}`),
    [
      `${ROOT}@0`,
      "auto_row_copy@1",
      "rect_accent_bar@1",
      "line_divider@1",
      "image_hero@1",
    ],
  );
});
