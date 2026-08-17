import assert from "node:assert/strict";
import test from "node:test";
import { HARVESTED_PAGE } from "./__fixtures__/web-nodes";
import { buildWebLayerRows } from "./layers";

// W2.3: rows from the real document hierarchy, nesting capped at depth 1
// (ruling 41). The fixture is the harvested page: root → hero(headline, sub,
// cta) + features(fgrid → fimg/ficon/fembed) — fgrid's children sit at depth
// 2 and must not appear.

test("rows come from the hierarchy in child order, capped at depth 1", () => {
  const rows = buildWebLayerRows(HARVESTED_PAGE, null);
  assert.deepEqual(
    rows.map((row) => `${row.nodeId}@${row.depth}`),
    [
      "hero@0",
      "headline@1",
      "sub@1",
      "cta@1",
      "features@0",
      "fgrid@1",
    ],
  );
  // Depth-2 nodes are capped out entirely.
  assert.ok(!rows.some((row) => ["fimg", "ficon", "fembed"].includes(row.nodeId)));
});

test("labels prefer the authored name and fall back to the node id", () => {
  const rows = buildWebLayerRows(HARVESTED_PAGE, null);
  const byId = new Map(rows.map((row) => [row.nodeId, row]));
  assert.equal(byId.get("hero")?.label, "Hero");
  assert.equal(byId.get("headline")?.label, "Headline");
  // A node without a name shows its id.
  const unnamed = buildWebLayerRows(
    {
      ...HARVESTED_PAGE,
      nodes: {
        ...HARVESTED_PAGE.nodes,
        hero: { ...HARVESTED_PAGE.nodes.hero, name: undefined },
      },
    },
    null,
  );
  assert.equal(unnamed.find((row) => row.nodeId === "hero")?.label, "hero");
});

test("kind → icon uses the dummy's icon vocabulary", () => {
  const rows = buildWebLayerRows(HARVESTED_PAGE, null);
  const icon = (id: string) => rows.find((row) => row.nodeId === id)?.icon;
  assert.equal(icon("hero"), "div"); // section
  assert.equal(icon("fgrid"), "div"); // container
  assert.equal(icon("headline"), "type"); // text
  assert.equal(icon("cta"), "rectangle"); // button
  // image/icon kinds sit at depth 2 in the fixture; verify via a direct page.
  const flat = buildWebLayerRows(
    {
      page_root: "root",
      nodes: {
        root: { id: "root", kind: "container", classes: "", children: ["i", "ic", "e"] },
        i: { id: "i", kind: "image", classes: "" },
        ic: { id: "ic", kind: "icon", classes: "" },
        e: { id: "e", kind: "embed", classes: "" },
      },
    },
    null,
  );
  assert.equal(flat.find((row) => row.nodeId === "i")?.icon, "image");
  assert.equal(flat.find((row) => row.nodeId === "ic")?.icon, "apple");
  assert.equal(flat.find((row) => row.nodeId === "e")?.icon, "div"); // fallback
});

test("only depth-0 rows with children are expandable under the cap", () => {
  const rows = buildWebLayerRows(HARVESTED_PAGE, null);
  const byId = new Map(rows.map((row) => [row.nodeId, row]));
  assert.equal(byId.get("hero")?.expandable, true);
  assert.equal(byId.get("features")?.expandable, true);
  assert.equal(byId.get("headline")?.expandable, false);
  // fgrid HAS children, but they are beyond the cap — not expandable.
  assert.equal(byId.get("fgrid")?.expandable, false);
});

test("depth-1 rows carry their parent id for collapse filtering", () => {
  const rows = buildWebLayerRows(HARVESTED_PAGE, null);
  const byId = new Map(rows.map((row) => [row.nodeId, row]));
  assert.equal(byId.get("headline")?.parentId, "hero");
  assert.equal(byId.get("fgrid")?.parentId, "features");
  assert.equal(byId.get("hero")?.parentId, null);
});

test("the active row follows the selected node id", () => {
  const rows = buildWebLayerRows(HARVESTED_PAGE, "cta");
  assert.deepEqual(
    rows.filter((row) => row.active).map((row) => row.nodeId),
    ["cta"],
  );
  assert.ok(buildWebLayerRows(HARVESTED_PAGE, null).every((row) => !row.active));
});

test("a missing or empty root yields no rows", () => {
  assert.deepEqual(buildWebLayerRows({ page_root: "nope", nodes: {} }, null), []);
});
