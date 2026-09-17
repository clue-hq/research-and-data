import type { NodeId, PageId, Scene } from "../engine/scene/contracts";
import { parentInfoForNode } from "../engine/scene/sceneQueries";
import { rootFrameId, sceneSelectionFor } from "./scene-hydrate";

/**
 * Selection model v2 (founder rulings 2026-09-04) — the pointer's selection
 * decisions, as pure functions.
 *
 * `representableHit` (AD2.5) picks the DEEPEST node under the pointer that has
 * an inspector schema, which on a real ad means a click almost always lands on
 * a leaf: the group is unreachable except through its padding, and a button is
 * selectable only in the gap around its label. Plan 3 answered that with a
 * button promotion plus "a second click on the already-selected node walks up".
 * That second-click rule is now REMOVED — a double-click is two clicks at one
 * spot, so walking up on the second click and drilling down on the double-click
 * cannot both be true of the same gesture. (Its 4 px slop constant,
 * `WALK_UP_CLICK_SLOP_PX`, and `selectionLadderHit` go with it.)
 *
 * What replaces it, per the six rules:
 *   R1 a click selects the OUTERMOST unit — a button or a group — on the path,
 *      or else the deepest representable node (`selectionClickTarget`);
 *   R2 a double-click drills one representable level toward the pointer
 *      (`selectionDrillDown`), and opens the caret only once the text itself is
 *      the selection (that gate lives in `scene-text-edit`);
 *   R3 Cmd/Ctrl-click selects the deepest node and cycles shallower on repeat
 *      (`deepSelectTarget`);
 *   R4 Alt-click and Escape walk up (`selectionWalkUp`, `escapeSelectionEffect`
 *      — both unchanged from Plan 3);
 *   R5 the hover outline previews R1's click target (`sceneHoverTarget`);
 *   R6 a press drags whatever the click selected (`selectionPressTarget`) —
 *      which is R1's target UNLESS the node already selected is under the
 *      pointer at or below it, in which case the press keeps the selection so
 *      a drilled-into label can actually be dragged (live proof 2026-09-04).
 *
 * The component around it owns events; everything decidable is decided here and
 * proven over the harvested ad.
 */

function presentChildren(scene: Scene, nodeId: NodeId): NodeId[] {
  const node = scene.nodes[nodeId];
  return node ? node.children.filter((id) => scene.nodes[id] !== undefined) : [];
}

/** R1: an auto-layout whose ONLY child is a text node. */
export function isButtonShaped(scene: Scene, nodeId: NodeId): boolean {
  return buttonLabelId(scene, nodeId) !== null;
}

/** The button's label — its single text child — or null when `nodeId` is not a button. */
export function buttonLabelId(scene: Scene, nodeId: NodeId): NodeId | null {
  const node = scene.nodes[nodeId];
  if (!node || node.kind.kind !== "auto_layout") {
    return null;
  }
  const children = presentChildren(scene, nodeId);
  if (children.length !== 1) {
    return null;
  }
  return scene.nodes[children[0]].kind.kind === "text" ? children[0] : null;
}

function representable(scene: Scene, pageId: PageId | null, nodeId: NodeId): boolean {
  const node = scene.nodes[nodeId];
  if (!node) {
    return false;
  }
  const root = pageId ? rootFrameId(scene, pageId) : null;
  return sceneSelectionFor(node, root) !== null;
}

/**
 * R1: a node the click treats as one thing rather than as scaffolding — a
 * button (Plan 3's shape) or a group. Frames and ordinary stacks are
 * pass-through: they hold their children apart, they are not the thing the
 * pointer is aiming at.
 */
export function isUnit(scene: Scene, nodeId: NodeId): boolean {
  const node = scene.nodes[nodeId];
  if (!node) {
    return false;
  }
  return node.kind.kind === "group" || isButtonShaped(scene, nodeId);
}

/** The stack's representable members, outer→inner. */
function representableStack(stack: NodeId[], scene: Scene, pageId: PageId | null): NodeId[] {
  return stack.filter((id) => representable(scene, pageId, id));
}

/**
 * R1: the click target. The OUTERMOST representable unit on the path wins; a
 * path without a unit selects the deepest representable node. Pass-through
 * containers therefore win a click only on their own empty area, where they
 * are the deepest hit.
 */
export function selectionClickTarget(
  stack: NodeId[],
  scene: Scene,
  pageId: PageId | null,
): NodeId | null {
  const candidates = representableStack(stack, scene, pageId);
  const unit = candidates.find((id) => isUnit(scene, id));
  return unit ?? candidates[candidates.length - 1] ?? null;
}

/**
 * R2: one level down toward the pointer — the representable child of the
 * selection on the path to the deepest hit. Null when the selection is not a
 * proper ancestor of the hit (nothing to drill into), which is what lets the
 * caller fall through to the caret.
 */
export function selectionDrillDown({
  stack,
  scene,
  pageId,
  selectedNodeId,
}: {
  stack: NodeId[];
  scene: Scene;
  pageId: PageId | null;
  selectedNodeId: NodeId | null;
}): NodeId | null {
  if (selectedNodeId === null) {
    return null;
  }
  const candidates = representableStack(stack, scene, pageId);
  const at = stack.indexOf(selectedNodeId);
  if (at === -1 || at === stack.length - 1) {
    return null;
  }
  return candidates.find((id) => stack.indexOf(id) > at) ?? null;
}

/**
 * R3: Cmd/Ctrl-click — the deepest representable node, so any leaf is one
 * gesture away however deep it sits; when the selection is already one of the
 * stack's representable members, the next SHALLOWER one, wrapping from the
 * outermost back to the deepest, so repeating the gesture walks the whole
 * stack without ever dead-ending.
 *
 * The ROOT FRAME is excluded from the cycle (founder ruling 2026-09-04). It is
 * representable — `sceneSelectionFor` maps it to the page's "canvas" selection
 * — but the artboard is the page itself, not a thing under the pointer: it is
 * what Escape lands on after everything else has been left, so a Cmd-click
 * should never stop there mid-cycle. It therefore wraps from the outermost
 * NON-root node, and a stack of nothing but the root selects nothing.
 * Escape and Alt-click still reach it, unchanged.
 */
export function deepSelectTarget({
  stack,
  scene,
  pageId,
  selectedNodeId,
}: {
  stack: NodeId[];
  scene: Scene;
  pageId: PageId | null;
  selectedNodeId: NodeId | null;
}): NodeId | null {
  const root = pageId ? rootFrameId(scene, pageId) : null;
  const candidates = representableStack(stack, scene, pageId).filter((id) => id !== root);
  if (candidates.length === 0) {
    return null;
  }
  const deepest = candidates[candidates.length - 1];
  const at = selectedNodeId === null ? -1 : candidates.indexOf(selectedNodeId);
  if (at === -1) {
    return deepest;
  }
  return at === 0 ? deepest : candidates[at - 1];
}

/** R4: the nearest representable ancestor; null from the root frame or an unknown node. */
export function selectionWalkUp(
  scene: Scene,
  pageId: PageId | null,
  nodeId: NodeId,
): NodeId | null {
  let current: NodeId = nodeId;
  if (!scene.nodes[current]) {
    return null;
  }
  for (;;) {
    const info = parentInfoForNode(scene, current);
    if (!info || info.parent.kind !== "node") {
      return null;
    }
    if (representable(scene, pageId, info.parent.id)) {
      return info.parent.id;
    }
    current = info.parent.id;
  }
}

/**
 * R6: what a plain press acts on. R1's click target — unless the node that is
 * ALREADY selected sits under the pointer at or below that target, in which
 * case the press keeps the selection and drags it. This is what makes a label
 * reached by drill-down movable: without it the press re-selected the enclosing
 * button and moved the button (Brex ad, live proof 2026-09-04, undone). An
 * ancestor selection does NOT survive — pressing a child inside a selected
 * container selects the child, the ordinary R1 answer.
 */
export function selectionPressTarget({
  stack,
  scene,
  pageId,
  selectedNodeId,
}: {
  stack: NodeId[];
  scene: Scene;
  pageId: PageId | null;
  selectedNodeId: NodeId | null;
}): NodeId | null {
  const target = selectionClickTarget(stack, scene, pageId);
  if (target === null || selectedNodeId === null) {
    return target;
  }
  const selectedAt = stack.indexOf(selectedNodeId);
  return selectedAt >= stack.indexOf(target) ? selectedNodeId : target;
}

/**
 * R5: what the hover outline shows — the node a press would act on, unless
 * that is already the selection (an outline over its own selection says
 * nothing). It follows R6 rather than R1 so the preview never promises the
 * button while the selected label under the pointer is what the press moves.
 */
export function sceneHoverTarget({
  stack,
  scene,
  pageId,
  selectedNodeId,
}: {
  stack: NodeId[];
  scene: Scene;
  pageId: PageId | null;
  selectedNodeId: NodeId | null;
}): NodeId | null {
  const hit = selectionPressTarget({ stack, scene, pageId, selectedNodeId });
  return hit !== null && hit !== selectedNodeId ? hit : null;
}

export type EscapeSelectionEffect =
  | { kind: "reset-gesture" }
  | { kind: "select"; nodeId: NodeId | null }
  | { kind: "none" };

/** R4: Escape — a live gesture resets (ruling C-2, unchanged); a caret owns its own Escape; otherwise walk up, clearing at the root. */
export function escapeSelectionEffect({
  gestureLive,
  textEditing,
  selectedNodeId,
  scene,
  pageId,
}: {
  gestureLive: boolean;
  textEditing: boolean;
  selectedNodeId: NodeId | null;
  scene: Scene | null;
  pageId: PageId | null;
}): EscapeSelectionEffect {
  if (gestureLive) {
    return { kind: "reset-gesture" };
  }
  if (textEditing || !scene || selectedNodeId === null || !scene.nodes[selectedNodeId]) {
    return { kind: "none" };
  }
  return { kind: "select", nodeId: selectionWalkUp(scene, pageId, selectedNodeId) };
}
