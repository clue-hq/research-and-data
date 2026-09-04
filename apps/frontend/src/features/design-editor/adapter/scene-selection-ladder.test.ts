import assert from "node:assert/strict";
import { it } from "node:test";
import type { Scene } from "../engine/scene/contracts";
import { AD_PAGE_ID, HARVESTED_AD_PAGE } from "./__fixtures__/scene-nodes";
import { representableHit } from "./scene-selection";
import {
  WALK_UP_CLICK_SLOP_PX,
  buttonLabelId,
  escapeSelectionEffect,
  isButtonShaped,
  sceneHoverTarget,
  selectionBreadcrumb,
  selectionLadderHit,
  selectionWalkUp,
} from "./scene-selection-ladder";

/**
 * Editor Quality Plan 3 (item E): the selection ladder. Every case runs over
 * the harvested ad; the one shape the harvest lacks — a BUTTON, an auto-layout
 * whose only child is text — is made by moving the real headline into the real
 * copy row (AD2.4's one-field-edit technique), never by inventing a node.
 */

function clone(scene: Scene): Scene {
  return JSON.parse(JSON.stringify(scene)) as Scene;
}

/** `auto_row_copy` becomes a button: its only child is `text_headline`. */
function sceneWithButton(): Scene {
  const next = clone(HARVESTED_AD_PAGE);
  for (const node of Object.values(next.nodes)) {
    node.children = node.children.filter((id) => id !== "text_headline");
  }
  for (const page of Object.values(next.pages)) {
    page.children = page.children.filter((id) => id !== "text_headline");
  }
  next.nodes.auto_row_copy.children = ["text_headline"];
  return next;
}

it("R1: an auto-layout whose only child is text is button-shaped; the harvest's row is not", () => {
  const scene = sceneWithButton();
  assert.equal(isButtonShaped(scene, "auto_row_copy"), true);
  assert.equal(buttonLabelId(scene, "auto_row_copy"), "text_headline");
  assert.equal(isButtonShaped(HARVESTED_AD_PAGE, "auto_row_copy"), false);
  assert.equal(buttonLabelId(HARVESTED_AD_PAGE, "auto_row_copy"), null);
  // A text node, a group and the root frame are never buttons.
  assert.equal(isButtonShaped(scene, "text_headline"), false);
  assert.equal(isButtonShaped(scene, "group_proof"), false);
  assert.equal(isButtonShaped(scene, "frame_ad_root"), false);
});

it("button-first: a hit on the label selects the BUTTON, while representableHit still says the label", () => {
  const scene = sceneWithButton();
  const stack = ["frame_ad_root", "auto_row_copy", "text_headline"];
  assert.equal(representableHit(stack, scene, AD_PAGE_ID), "text_headline");
  assert.equal(selectionLadderHit(stack, scene, AD_PAGE_ID), "auto_row_copy");
});

it("everything else keeps deepest-leaf first click", () => {
  // The harvest's row is not a button, so its text descendant wins as before.
  const stack = ["frame_ad_root", "auto_row_copy", "group_proof", "text_proof_stat"];
  assert.equal(selectionLadderHit(stack, HARVESTED_AD_PAGE, AD_PAGE_ID), "text_proof_stat");
  assert.equal(selectionLadderHit([], HARVESTED_AD_PAGE, AD_PAGE_ID), null);
  assert.equal(selectionLadderHit(["line_divider"], HARVESTED_AD_PAGE, AD_PAGE_ID), null);
});

it("R2: walk-up climbs to the nearest representable ancestor and stops at the root frame", () => {
  assert.equal(selectionWalkUp(HARVESTED_AD_PAGE, AD_PAGE_ID, "text_proof_stat"), "group_proof");
  assert.equal(selectionWalkUp(HARVESTED_AD_PAGE, AD_PAGE_ID, "group_proof"), "auto_row_copy");
  assert.equal(selectionWalkUp(HARVESTED_AD_PAGE, AD_PAGE_ID, "auto_row_copy"), "frame_ad_root");
  assert.equal(selectionWalkUp(HARVESTED_AD_PAGE, AD_PAGE_ID, "frame_ad_root"), null);
  assert.equal(selectionWalkUp(HARVESTED_AD_PAGE, AD_PAGE_ID, "no_such_node"), null);
});

it("hover: the ladder hit, unless it is the selected node itself", () => {
  const stack = ["frame_ad_root", "auto_row_copy", "group_proof", "text_proof_stat"];
  assert.equal(
    sceneHoverTarget({ stack, scene: HARVESTED_AD_PAGE, pageId: AD_PAGE_ID, selectedNodeId: null }),
    "text_proof_stat",
  );
  assert.equal(
    sceneHoverTarget({ stack, scene: HARVESTED_AD_PAGE, pageId: AD_PAGE_ID, selectedNodeId: "text_proof_stat" }),
    null,
  );
  // Over a button, the hover target is the button (what a click would select).
  const scene = sceneWithButton();
  assert.equal(
    sceneHoverTarget({
      stack: ["frame_ad_root", "auto_row_copy", "text_headline"],
      scene,
      pageId: AD_PAGE_ID,
      selectedNodeId: null,
    }),
    "auto_row_copy",
  );
  assert.equal(
    sceneHoverTarget({ stack: [], scene: HARVESTED_AD_PAGE, pageId: AD_PAGE_ID, selectedNodeId: null }),
    null,
  );
});

it("R3 Escape: a live gesture resets; a caret is left alone; otherwise the selection walks up, and clears at the root", () => {
  const base = { scene: HARVESTED_AD_PAGE, pageId: AD_PAGE_ID };
  assert.deepEqual(
    escapeSelectionEffect({ ...base, gestureLive: true, textEditing: false, selectedNodeId: "group_proof" }),
    { kind: "reset-gesture" },
  );
  assert.deepEqual(
    escapeSelectionEffect({ ...base, gestureLive: false, textEditing: true, selectedNodeId: "group_proof" }),
    { kind: "none" },
  );
  assert.deepEqual(
    escapeSelectionEffect({ ...base, gestureLive: false, textEditing: false, selectedNodeId: "group_proof" }),
    { kind: "select", nodeId: "auto_row_copy" },
  );
  assert.deepEqual(
    escapeSelectionEffect({ ...base, gestureLive: false, textEditing: false, selectedNodeId: "frame_ad_root" }),
    { kind: "select", nodeId: null },
  );
  assert.deepEqual(
    escapeSelectionEffect({ ...base, gestureLive: false, textEditing: false, selectedNodeId: null }),
    { kind: "none" },
  );
  assert.deepEqual(
    escapeSelectionEffect({ scene: null, pageId: null, gestureLive: false, textEditing: false, selectedNodeId: "x" }),
    { kind: "none" },
  );
});

it("breadcrumb: representable ancestry from the root frame down to the node, with display names", () => {
  const crumbs = selectionBreadcrumb(HARVESTED_AD_PAGE, AD_PAGE_ID, "text_proof_stat");
  assert.deepEqual(
    crumbs.map((crumb) => crumb.nodeId),
    ["frame_ad_root", "auto_row_copy", "group_proof", "text_proof_stat"],
  );
  assert.equal(crumbs[1].label, "Copy row");
  assert.deepEqual(selectionBreadcrumb(HARVESTED_AD_PAGE, AD_PAGE_ID, null), []);
  assert.deepEqual(selectionBreadcrumb(HARVESTED_AD_PAGE, AD_PAGE_ID, "no_such_node"), []);
});

it("the same-spot walk-up slop is four screen pixels", () => {
  assert.equal(WALK_UP_CLICK_SLOP_PX, 4);
});
