import assert from "node:assert/strict";
import test from "node:test";
import type { NodeId, Scene } from "../engine/scene/contracts";
import type { WorkspaceViewport } from "../engine/scene/workspaceViewport";
import { AD_PAGE_ID, HARVESTED_AD_PAGE } from "./__fixtures__/scene-nodes";
import { sceneArtboardModel } from "./scene-canvas-view";
import {
  MIN_TEXT_EDIT_SIZE_PX,
  SCENE_TEXT_EDIT_INTENT,
  sceneDoubleClickEffect,
  sceneTextEditModel,
  textEditCommitOperations,
} from "./scene-text-edit";

/**
 * Rung B (rich-text plan, 2026-08-24): the pure decisions behind double-click
 * inline text editing — what a double-click resolves to, what geometry and
 * style the DOM overlay is drawn with, and what a committed draft writes.
 *
 * Every case runs against AD2.2's harvested bytes (the seeded
 * `doc_ad22linkedinsquare00000000001`), never a hand-written shape. The
 * harvest carries `computed: null` on every node — the honest at-rest state —
 * so a case that needs a laid-out box injects the geometry the engine's
 * relayout would produce, on a CLONE, exactly as the AD4.C suite does.
 */

function clone(scene: Scene): Scene {
  return JSON.parse(JSON.stringify(scene)) as Scene;
}

/** `text_proof_stat`'s laid-out box: a plain (non-token) text node, so its
 * descriptor fill resolves with no brand kit loaded. */
const STAT_BOX = { x: 780, y: 149, width: 256, height: 36 };

function sceneWithLaidOutStat(): Scene {
  const scene = clone(HARVESTED_AD_PAGE);
  scene.nodes.text_proof_stat.computed = {
    layout_bounds: { ...STAT_BOX },
    render_bounds: { ...STAT_BOX },
  };
  return scene;
}

function artboardFor(scene: Scene) {
  const artboard = sceneArtboardModel(scene, AD_PAGE_ID);
  assert.ok(artboard);
  return artboard;
}

const UNIT_VIEWPORT: WorkspaceViewport = { zoom: 1, pan: { x: 0, y: 0 } };

function modelFor(
  scene: Scene,
  {
    editingNodeId = "text_proof_stat" as NodeId | null,
    viewport = UNIT_VIEWPORT,
  } = {},
) {
  return sceneTextEditModel({
    artboard: artboardFor(scene),
    editingNodeId,
    pageId: AD_PAGE_ID,
    scene,
    viewport,
  });
}

/* -------------------------------------------------------------------------
 * The double-click itself — open a session, or drill out
 * ---------------------------------------------------------------------- */

test("a double-click on a text node opens an edit session on it", () => {
  const effect = sceneDoubleClickEffect({
    gestureDisabled: false,
    nodeId: "text_headline",
    scene: HARVESTED_AD_PAGE,
    selectedNodeId: "text_headline",
  });
  assert.deepEqual(effect, { kind: "edit", nodeId: "text_headline" });
});

test("a LOCKED text node opens no session — the lock gates every write path", () => {
  const scene = clone(HARVESTED_AD_PAGE);
  scene.nodes.text_headline.locked = true;
  assert.deepEqual(
    sceneDoubleClickEffect({
      gestureDisabled: false,
      nodeId: "text_headline",
      scene,
      selectedNodeId: "text_headline",
    }),
    { kind: "none" },
  );
});

test("Gate G-H: no session opens while an agent turn is in flight", () => {
  assert.deepEqual(
    sceneDoubleClickEffect({
      gestureDisabled: true,
      nodeId: "text_headline",
      scene: HARVESTED_AD_PAGE,
      selectedNodeId: "text_headline",
    }),
    { kind: "none" },
  );
});

test("Ruling C-9 does not apply: a layout-MANAGED text node still opens a session", () => {
  // `text_headline` is a child of the `auto_row_copy` row — solver-owned. A
  // content edit re-solves the layout, so no freeze-on-grab fires for it.
  assert.deepEqual(
    sceneDoubleClickEffect({
      gestureDisabled: false,
      nodeId: "text_headline",
      scene: HARVESTED_AD_PAGE,
      selectedNodeId: "text_headline",
    }),
    { kind: "edit", nodeId: "text_headline" },
  );
});

test("a non-text hit drills out to its top-level container", () => {
  assert.deepEqual(
    sceneDoubleClickEffect({
      gestureDisabled: false,
      nodeId: "ellipse_proof_dot",
      scene: HARVESTED_AD_PAGE,
      selectedNodeId: "ellipse_proof_dot",
    }),
    { kind: "select", nodeId: "frame_ad_root" },
  );
});

test("a hit that is already top-level drills nowhere", () => {
  assert.deepEqual(
    sceneDoubleClickEffect({
      gestureDisabled: false,
      nodeId: "frame_ad_root",
      scene: HARVESTED_AD_PAGE,
      selectedNodeId: "frame_ad_root",
    }),
    { kind: "none" },
  );
});

test("a double-click on nothing drills out from the current selection", () => {
  assert.deepEqual(
    sceneDoubleClickEffect({
      gestureDisabled: false,
      nodeId: null,
      scene: HARVESTED_AD_PAGE,
      selectedNodeId: "ellipse_proof_dot",
    }),
    { kind: "select", nodeId: "frame_ad_root" },
  );
});

test("a double-click on nothing with nothing selected decides nothing", () => {
  assert.deepEqual(
    sceneDoubleClickEffect({
      gestureDisabled: false,
      nodeId: null,
      scene: HARVESTED_AD_PAGE,
      selectedNodeId: null,
    }),
    { kind: "none" },
  );
});

test("no scene — no session and no drill-out", () => {
  assert.deepEqual(
    sceneDoubleClickEffect({
      gestureDisabled: false,
      nodeId: "text_headline",
      scene: null,
      selectedNodeId: "text_headline",
    }),
    { kind: "none" },
  );
});

/* -------------------------------------------------------------------------
 * The commit — ONE batch, or nothing at all
 * ---------------------------------------------------------------------- */

test("a changed draft commits as ONE update_node batch (one undo frame)", () => {
  const node = HARVESTED_AD_PAGE.nodes.text_proof_stat;
  const operations = textEditCommitOperations(node, "4.1x faster triage");
  assert.ok(operations);
  assert.equal(operations.length, 1);
  const [operation] = operations;
  assert.equal(operation.kind, "update_node");
  assert.equal(operation.node_id, "text_proof_stat");
  assert.deepEqual(operation.patch.kind, {
    kind: "set",
    value: { ...node.kind, content: "4.1x faster triage" },
  });
});

test("an unchanged draft writes NOTHING — a blur that typed nothing is not an edit", () => {
  const node = HARVESTED_AD_PAGE.nodes.text_proof_stat;
  assert.equal(textEditCommitOperations(node, node.kind.content as string), null);
});

test("the empty string is a legal commit — a node that says nothing is a real edit", () => {
  const operations = textEditCommitOperations(
    HARVESTED_AD_PAGE.nodes.text_proof_stat,
    "",
  );
  assert.ok(operations);
  assert.equal(operations.length, 1);
});

test("a locked node commits nothing — the write-side lock gate, restated", () => {
  const scene = clone(HARVESTED_AD_PAGE);
  scene.nodes.text_proof_stat.locked = true;
  assert.equal(textEditCommitOperations(scene.nodes.text_proof_stat, "new"), null);
});

test("a non-text node commits nothing", () => {
  assert.equal(
    textEditCommitOperations(HARVESTED_AD_PAGE.nodes.ellipse_proof_dot, "new"),
    null,
  );
});

test("D10: a node the reload took away commits nothing", () => {
  assert.equal(textEditCommitOperations(null, "new"), null);
});

test("the write says which surface it came from", () => {
  assert.equal(SCENE_TEXT_EDIT_INTENT, "canvas: text edit");
});

/* -------------------------------------------------------------------------
 * The overlay model — geometry in stage px, style off the descriptor
 * ---------------------------------------------------------------------- */

test("the overlay covers the node's laid-out box, in stage px", () => {
  const model = modelFor(sceneWithLaidOutStat());
  assert.ok(model);
  assert.equal(model.nodeId, "text_proof_stat");
  assert.equal(model.left, STAT_BOX.x);
  assert.equal(model.top, STAT_BOX.y);
  assert.equal(model.width, STAT_BOX.width);
  assert.equal(model.height, STAT_BOX.height);
  assert.equal(model.rotation, 0);
});

test("the overlay edits the STORED content, not the painted text", () => {
  const scene = sceneWithLaidOutStat();
  // `text_transform` applies to painted glyphs only; the caret edits what is
  // stored, so the overlay must show the stored string unchanged.
  scene.nodes.text_proof_stat.kind.text_transform = "uppercase";
  const model = modelFor(scene);
  assert.ok(model);
  assert.equal(model.content, "3.4x faster triage");
});

test("the overlay is style-matched to the painted node", () => {
  const model = modelFor(sceneWithLaidOutStat());
  assert.ok(model);
  assert.deepEqual(model.style, {
    color: "#C7C2F5",
    fontFamily: "Inter",
    fontSize: 26,
    fontStyle: "normal",
    fontWeight: 600,
    letterSpacing: 0,
    lineHeight: 1.35,
    textAlign: "left",
    valign: "top",
  });
});

test("block italic reaches the edit surface, so the caret sits in matching glyphs", () => {
  const scene = sceneWithLaidOutStat();
  scene.nodes.text_proof_stat.kind.italic = true;
  const model = modelFor(scene);
  assert.ok(model);
  assert.equal(model.style.fontStyle, "italic");
});

test("zoom scales the box AND the font metrics together", () => {
  const scene = sceneWithLaidOutStat();
  scene.nodes.text_proof_stat.kind.letter_spacing = 2;
  const model = modelFor(scene, {
    viewport: { zoom: 2, pan: { x: 0, y: 0 } },
  });
  assert.ok(model);
  assert.equal(model.left, STAT_BOX.x * 2);
  assert.equal(model.width, STAT_BOX.width * 2);
  assert.equal(model.height, STAT_BOX.height * 2);
  assert.equal(model.style.fontSize, 52);
  assert.equal(model.style.letterSpacing, 4);
  // A ratio, never a length — it must not be scaled.
  assert.equal(model.style.lineHeight, 1.35);
});

test("a pan moves the overlay with the pixels it sits over", () => {
  const model = modelFor(sceneWithLaidOutStat(), {
    viewport: { zoom: 1, pan: { x: 40, y: -25 } },
  });
  assert.ok(model);
  assert.equal(model.left, STAT_BOX.x + 40);
  assert.equal(model.top, STAT_BOX.y - 25);
});

test("a degenerate box still leaves a grabbable caret", () => {
  const scene = sceneWithLaidOutStat();
  scene.nodes.text_proof_stat.computed = {
    layout_bounds: { x: 10, y: 20, width: 0, height: 0 },
    render_bounds: { x: 10, y: 20, width: 0, height: 0 },
  };
  const model = modelFor(scene);
  assert.ok(model);
  assert.equal(model.width, MIN_TEXT_EDIT_SIZE_PX);
  assert.equal(model.height, MIN_TEXT_EDIT_SIZE_PX);
});

test("an unsolved node has no overlay — a guessed box would draw the caret elsewhere", () => {
  assert.equal(modelFor(HARVESTED_AD_PAGE), null);
});

test("D10: a node the reload took away closes the session", () => {
  const scene = sceneWithLaidOutStat();
  assert.equal(modelFor(scene, { editingNodeId: "text_gone" }), null);
});

test("a non-text node has no overlay", () => {
  const scene = clone(HARVESTED_AD_PAGE);
  scene.nodes.ellipse_proof_dot.computed = {
    layout_bounds: { ...STAT_BOX },
    render_bounds: { ...STAT_BOX },
  };
  assert.equal(modelFor(scene, { editingNodeId: "ellipse_proof_dot" }), null);
});

test("no session, no overlay", () => {
  assert.equal(modelFor(sceneWithLaidOutStat(), { editingNodeId: null }), null);
});
