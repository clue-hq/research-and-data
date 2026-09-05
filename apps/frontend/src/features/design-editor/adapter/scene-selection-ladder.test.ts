import assert from "node:assert/strict";
import { it } from "node:test";
import type { Scene } from "../engine/scene/contracts";
import { AD_PAGE_ID, HARVESTED_AD_PAGE } from "./__fixtures__/scene-nodes";
import { representableHit } from "./scene-selection";
import {
  buttonLabelId,
  deepSelectTarget,
  escapeSelectionEffect,
  isButtonShaped,
  isUnit,
  sceneHoverTarget,
  selectionClickTarget,
  selectionDrillDown,
  selectionPressTarget,
  selectionWalkUp,
} from "./scene-selection-ladder";

/**
 * Selection model v2 (founder rulings 2026-09-04): the click/drill/deep-select
 * decisions. Every case runs over the harvested ad; the one shape the harvest
 * lacks — a BUTTON, an auto-layout whose only child is text — is made by moving
 * the real headline into the real copy row (AD2.4's one-field-edit technique),
 * never by inventing a node.
 *
 * Plan 3's "second click on the selected node walks up" is gone (a double-click
 * is two clicks at one spot, so it cannot coexist with drilling), and with it
 * the slop constant and `selectionLadderHit`; the Escape and Alt-click walk-ups
 * are unchanged and keep their Plan 3 cases verbatim.
 *
 * On the harvest, the ROOT FRAME IS REPRESENTABLE — `sceneSelectionFor` maps it
 * to the page's "canvas" selection — so it is the last stop of a walk-up. The
 * R3 cycle nonetheless EXCLUDES it (founder ruling 2026-09-04): the artboard is
 * the page, reached by Escape, not something a Cmd-click should land on
 * mid-cycle. These cases pin both halves of that.
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
  assert.equal(isButtonShaped(scene, "text_headline"), false);
  assert.equal(isButtonShaped(scene, "group_proof"), false);
});

it("units are buttons and groups; frames, stacks and leaves are pass-through", () => {
  const scene = sceneWithButton();
  assert.equal(isUnit(scene, "auto_row_copy"), true);
  assert.equal(isUnit(HARVESTED_AD_PAGE, "group_proof"), true);
  assert.equal(isUnit(HARVESTED_AD_PAGE, "auto_row_copy"), false);
  assert.equal(isUnit(HARVESTED_AD_PAGE, "frame_ad_root"), false);
  assert.equal(isUnit(HARVESTED_AD_PAGE, "text_proof_stat"), false);
});

it("R1 click: the OUTERMOST unit on the path wins; without a unit, the deepest representable node", () => {
  const scene = sceneWithButton();
  assert.equal(
    selectionClickTarget(["frame_ad_root", "auto_row_copy", "text_headline"], scene, AD_PAGE_ID),
    "auto_row_copy",
  );
  // The harvest's row is not a unit but `group_proof` is: the group wins over its member.
  const stack = ["frame_ad_root", "auto_row_copy", "group_proof", "text_proof_stat"];
  assert.equal(representableHit(stack, HARVESTED_AD_PAGE, AD_PAGE_ID), "text_proof_stat");
  assert.equal(selectionClickTarget(stack, HARVESTED_AD_PAGE, AD_PAGE_ID), "group_proof");
  // No unit on the path: deepest representable.
  assert.equal(
    selectionClickTarget(["frame_ad_root", "auto_row_copy", "text_proof_stat"], HARVESTED_AD_PAGE, AD_PAGE_ID),
    "text_proof_stat",
  );
  // A pass-through container is the target only on its own empty area.
  assert.equal(
    selectionClickTarget(["frame_ad_root", "auto_row_copy"], HARVESTED_AD_PAGE, AD_PAGE_ID),
    "auto_row_copy",
  );
  assert.equal(selectionClickTarget([], HARVESTED_AD_PAGE, AD_PAGE_ID), null);
  // An unrepresentable-only stack clears the selection rather than guessing.
  assert.equal(selectionClickTarget(["line_divider"], HARVESTED_AD_PAGE, AD_PAGE_ID), null);
});

it("R2 drill: from an ancestor, one representable level toward the pointer; from the leaf, nothing", () => {
  const stack = ["frame_ad_root", "auto_row_copy", "group_proof", "text_proof_stat"];
  assert.equal(
    selectionDrillDown({
      stack,
      scene: HARVESTED_AD_PAGE,
      pageId: AD_PAGE_ID,
      selectedNodeId: "auto_row_copy",
    }),
    "group_proof",
  );
  assert.equal(
    selectionDrillDown({
      stack,
      scene: HARVESTED_AD_PAGE,
      pageId: AD_PAGE_ID,
      selectedNodeId: "group_proof",
    }),
    "text_proof_stat",
  );
  assert.equal(
    selectionDrillDown({
      stack,
      scene: HARVESTED_AD_PAGE,
      pageId: AD_PAGE_ID,
      selectedNodeId: "text_proof_stat",
    }),
    null,
  );
  // Not an ancestor of the hit: nothing to drill.
  assert.equal(
    selectionDrillDown({
      stack,
      scene: HARVESTED_AD_PAGE,
      pageId: AD_PAGE_ID,
      selectedNodeId: "text_headline",
    }),
    null,
  );
  assert.equal(
    selectionDrillDown({ stack, scene: HARVESTED_AD_PAGE, pageId: AD_PAGE_ID, selectedNodeId: null }),
    null,
  );
  // The button: plate selected, a double-click on the label drills to the label.
  const button = sceneWithButton();
  assert.equal(
    selectionDrillDown({
      stack: ["frame_ad_root", "auto_row_copy", "text_headline"],
      scene: button,
      pageId: AD_PAGE_ID,
      selectedNodeId: "auto_row_copy",
    }),
    "text_headline",
  );
});

it("R3 deep select: the deepest node, then one shallower per repeat, wrapping to the deepest", () => {
  const stack = ["frame_ad_root", "auto_row_copy", "group_proof", "text_proof_stat"];
  const at = (selectedNodeId: string | null) =>
    deepSelectTarget({ stack, scene: HARVESTED_AD_PAGE, pageId: AD_PAGE_ID, selectedNodeId });
  assert.equal(at(null), "text_proof_stat");
  assert.equal(at("text_proof_stat"), "group_proof");
  assert.equal(at("group_proof"), "auto_row_copy");
  // The root frame is representable (it is the canvas selection) but is EXCLUDED
  // from the cycle, so the wrap happens at the row and a canvas selection starts
  // the cycle over rather than continuing from it.
  assert.equal(at("auto_row_copy"), "text_proof_stat");
  assert.equal(at("frame_ad_root"), "text_proof_stat");
  // A selection outside the stack starts over at the deepest.
  assert.equal(at("text_headline"), "text_proof_stat");
  // Nothing but the root under the pointer: nothing to deep-select.
  assert.equal(
    deepSelectTarget({
      stack: ["frame_ad_root"],
      scene: HARVESTED_AD_PAGE,
      pageId: AD_PAGE_ID,
      selectedNodeId: null,
    }),
    null,
  );
  assert.equal(
    deepSelectTarget({ stack: [], scene: HARVESTED_AD_PAGE, pageId: AD_PAGE_ID, selectedNodeId: null }),
    null,
  );
});

it("R4 walk-up climbs to the nearest representable ancestor and stops at the root frame", () => {
  assert.equal(selectionWalkUp(HARVESTED_AD_PAGE, AD_PAGE_ID, "text_proof_stat"), "group_proof");
  assert.equal(selectionWalkUp(HARVESTED_AD_PAGE, AD_PAGE_ID, "group_proof"), "auto_row_copy");
  assert.equal(selectionWalkUp(HARVESTED_AD_PAGE, AD_PAGE_ID, "auto_row_copy"), "frame_ad_root");
  assert.equal(selectionWalkUp(HARVESTED_AD_PAGE, AD_PAGE_ID, "frame_ad_root"), null);
  assert.equal(selectionWalkUp(HARVESTED_AD_PAGE, AD_PAGE_ID, "no_such_node"), null);
});

it("R5 hover: the click target, unless it is the selected node itself", () => {
  const stack = ["frame_ad_root", "auto_row_copy", "group_proof", "text_proof_stat"];
  assert.equal(
    sceneHoverTarget({ stack, scene: HARVESTED_AD_PAGE, pageId: AD_PAGE_ID, selectedNodeId: null }),
    "group_proof",
  );
  assert.equal(
    sceneHoverTarget({ stack, scene: HARVESTED_AD_PAGE, pageId: AD_PAGE_ID, selectedNodeId: "group_proof" }),
    null,
  );
  // Over a button, the hover target is the button — what a click would select.
  assert.equal(
    sceneHoverTarget({
      stack: ["frame_ad_root", "auto_row_copy", "text_headline"],
      scene: sceneWithButton(),
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

it("Escape: a live gesture resets; a caret is left alone; otherwise the selection walks up, and clears at the root", () => {
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
    escapeSelectionEffect({ ...base, gestureLive: false, textEditing: false, selectedNodeId: "text_proof_stat" }),
    { kind: "select", nodeId: "group_proof" },
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

it("R6: a press on the already-selected node keeps it, even inside a unit; an ancestor selection yields the click target", () => {
  const scene = sceneWithButton();
  const stack = ["frame_ad_root", "auto_row_copy", "text_headline"];
  // Nothing / something unrelated selected: the click target (the button).
  assert.equal(
    selectionPressTarget({ stack, scene, pageId: AD_PAGE_ID, selectedNodeId: null }),
    "auto_row_copy",
  );
  assert.equal(
    selectionPressTarget({ stack, scene, pageId: AD_PAGE_ID, selectedNodeId: "group_proof" }),
    "auto_row_copy",
  );
  // The label is selected (reached by drill-down): a press on it drags the LABEL.
  assert.equal(
    selectionPressTarget({ stack, scene, pageId: AD_PAGE_ID, selectedNodeId: "text_headline" }),
    "text_headline",
  );
  // The button itself selected: the button.
  assert.equal(
    selectionPressTarget({ stack, scene, pageId: AD_PAGE_ID, selectedNodeId: "auto_row_copy" }),
    "auto_row_copy",
  );
  // An ANCESTOR of the click target selected: the click target, not the ancestor.
  assert.equal(
    selectionPressTarget({ stack, scene, pageId: AD_PAGE_ID, selectedNodeId: "frame_ad_root" }),
    "auto_row_copy",
  );
  // Hover follows the press rule and stays silent on the selection itself.
  assert.equal(
    sceneHoverTarget({ stack, scene, pageId: AD_PAGE_ID, selectedNodeId: "text_headline" }),
    null,
  );
  assert.equal(
    sceneHoverTarget({ stack, scene, pageId: AD_PAGE_ID, selectedNodeId: "group_proof" }),
    "auto_row_copy",
  );
});
