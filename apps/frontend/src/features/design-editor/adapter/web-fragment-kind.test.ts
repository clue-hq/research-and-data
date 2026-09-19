/**
 * The editor tolerates a `fragment` node (clone-fidelity F1.3).
 *
 * F1.1 added `WebNodeKind::Fragment` to the engine's node union. The inspector UI for it is
 * Phase F3's, deliberately — but the moment a document carries one, the editor is handed it by
 * every read path it has, and "the editor crashes on a document it was handed" is not an
 * acceptable state to leave between phases.
 *
 * So this file proves the degrade rather than the feature: a fragment node flows through the
 * layer tree, the inspector schema resolver and the canvas gesture planners without throwing,
 * and each surface refuses it the way it already refuses every other kind it does not serve.
 * When F3 gives fragments real inspector affordances, these expectations change on purpose and
 * the change will be visible here.
 */
import { strict as assert } from "node:assert";
import { test } from "node:test";

import { inspectorSelectionFor } from "./hydrate";
import { buildWebLayerRows } from "./layers";
import {
  planCanvasNodeMove,
  planCanvasNodeResize,
  type WebNode,
} from "../engine/webDocuments";

const FRAGMENT: WebNode = {
  id: "frg_hero",
  kind: "fragment",
  classes: "w-full py-12",
  fragment_id: "frag_0123456789abcdef",
  slots: { headline: { text: "Talk to us" } }
};

const PAGE = {
  page_root: "root",
  root: "root",
  nodes: {
    root: { id: "root", kind: "container", classes: "", children: ["sec_a"] },
    sec_a: { id: "sec_a", kind: "section", classes: "", children: ["frg_hero"] },
    frg_hero: FRAGMENT
  } as Record<string, WebNode>
};

test("a fragment node appears in the layer tree instead of breaking it", () => {
  const rows = buildWebLayerRows(PAGE, "frg_hero");
  const row = rows.find((candidate) => candidate.nodeId === "frg_hero");
  assert.ok(row, "the fragment is listed");
  // Ruling R-A5 (founder, 2026-09-04): the label is a human name, never the raw
  // id (this used to read "frg_hero"). With no `fragment_meta` for this pin the
  // clone still names itself honestly rather than leaking its id.
  assert.equal(row?.label, "Cloned section");
  // No icon is mapped for the kind, so it takes the generic one rather than
  // rendering `undefined`.
  assert.equal(row?.icon, "div");
  assert.equal(row?.active, true);
});

test("the inspector falls back to layout-only rather than failing to resolve a schema", () => {
  const selection = inspectorSelectionFor(FRAGMENT, "root");
  assert.equal(selection.selection, "container");
  assert.equal(selection.layoutOnly, true);
});

test("the canvas reorders a fragment but never resizes it (D-F3)", () => {
  // Founder ruling D-F3, Option A: top-level reordering only. A whole cloned band moves up or
  // down the page; it is never manually resized, never a drop target, and stays a leaf.
  const page = {
    page_root: "root",
    root: "root",
    nodes: {
      root: { id: "root", kind: "container", classes: "", children: ["sec_a"] },
      sec_a: {
        id: "sec_a",
        kind: "section",
        classes: "",
        children: ["txt_a", "frg_hero"]
      },
      txt_a: { id: "txt_a", kind: "text", classes: "" },
      frg_hero: FRAGMENT
    } as Record<string, WebNode>
  };
  assert.equal(planCanvasNodeMove(page, "frg_hero", "sec_a", 0)?.intent, "reorder_node");
  assert.equal(planCanvasNodeResize(page, "frg_hero", 640, null), null);
  // An ordinary node dropped INSIDE the clone would be an internal edit of somebody else's
  // section; and the page root holds sections only, so the wrapper travels, not the fragment.
  assert.equal(planCanvasNodeMove(PAGE, "frg_hero", "root", 0), null);
});

test("a fragment inside a section does not stop its siblings from working", () => {
  const rows = buildWebLayerRows(
    {
      page_root: "root",
      root: "root",
      nodes: {
        root: { id: "root", kind: "container", classes: "", children: ["sec_a"] },
        sec_a: {
          id: "sec_a",
          kind: "section",
          classes: "",
          children: ["frg_hero", "txt_a"]
        },
        frg_hero: FRAGMENT,
        txt_a: { id: "txt_a", kind: "text", classes: "", name: "Headline" }
      } as Record<string, WebNode>
    },
    null
  );
  assert.deepEqual(
    rows.map((row) => row.nodeId),
    ["sec_a", "frg_hero", "txt_a"]
  );
});
