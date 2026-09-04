import type { NodeId, PageId, Scene } from "../engine/scene/contracts";
import { parentInfoForNode } from "../engine/scene/sceneQueries";
import { rootFrameId, sceneSelectionFor } from "./scene-hydrate";
import { representableHit } from "./scene-selection";

/**
 * Editor Quality Plan 3 (item E) — the selection ladder, as pure decisions.
 *
 * `representableHit` (AD2.5) picks the topmost node under the pointer that has
 * an inspector schema. Inside a button that is always the label text, so the
 * button itself was selectable only in its padding; there was no hover
 * feedback and no way to reach a parent from the canvas. This module adds the
 * rungs the roadmap ruled: button-as-a-unit on the first click, walk-up
 * (second click / Alt-click / Escape), a hover target, and the breadcrumb's
 * ancestry. The component around it owns events; everything decidable is
 * decided here and proven over the harvested ad.
 */

/** Pointer travel (screen px) under which a press-and-release counts as a click. */
export const WALK_UP_CLICK_SLOP_PX = 4;

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
 * The first-click selection: `representableHit`, promoted to the parent when
 * the hit is a button's label and the button is itself representable.
 */
export function selectionLadderHit(
  stack: NodeId[],
  scene: Scene,
  pageId: PageId | null,
): NodeId | null {
  const hit = representableHit(stack, scene, pageId);
  if (hit === null) {
    return null;
  }
  const node = scene.nodes[hit];
  if (node?.kind.kind !== "text") {
    return hit;
  }
  const info = parentInfoForNode(scene, hit);
  if (!info || info.parent.kind !== "node") {
    return hit;
  }
  const parentId = info.parent.id;
  if (buttonLabelId(scene, parentId) === hit && representable(scene, pageId, parentId)) {
    return parentId;
  }
  return hit;
}

/** R2: the nearest representable ancestor; null from the root frame or an unknown node. */
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

/** R4: what the hover outline shows — the click target, unless it is already selected. */
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
  const hit = selectionLadderHit(stack, scene, pageId);
  return hit !== null && hit !== selectedNodeId ? hit : null;
}

export type EscapeSelectionEffect =
  | { kind: "reset-gesture" }
  | { kind: "select"; nodeId: NodeId | null }
  | { kind: "none" };

/** R3: Escape — a live gesture resets (ruling C-2, unchanged); a caret owns its own Escape; otherwise walk up, clearing at the root. */
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
