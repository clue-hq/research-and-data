import type { Node, NodeId, Operation, Rect, Scene } from "./contracts";
import { updateNodeAbsoluteBox, updateNodeTransform } from "./operations";
import { isNodeFreehand, nodePageSpaceBox, parentComputedOrigin } from "./sceneQueries";

/** Alignment target: left/right edges and horizontal center map onto the
 * selection's union box on the x-axis; top/bottom/middle map onto the y-axis. */
export type AlignMode = "left" | "center-h" | "right" | "top" | "middle-v" | "bottom";

export type DistributeAxis = "horizontal" | "vertical";

export interface AlignDistributeItem {
  id: string;
  box: Rect;
}

export interface AlignDistributeTarget {
  id: string;
  box: Rect;
}

/** Union bounding box of every item's page-space box — the reference frame
 * every align mode measures against (Moda/Figma-style: align to selection,
 * not to any single member). */
function unionBox(items: AlignDistributeItem[]): Rect {
  const left = Math.min(...items.map((item) => item.box.x));
  const top = Math.min(...items.map((item) => item.box.y));
  const right = Math.max(...items.map((item) => item.box.x + item.box.width));
  const bottom = Math.max(...items.map((item) => item.box.y + item.box.height));
  return { x: left, y: top, width: right - left, height: bottom - top };
}

/**
 * Align 2+ page-space boxes against their union bounding box. Sizes never
 * change — only `x`/`y` move. Returns only the boxes whose position actually
 * changes, so a caller can skip a no-op commit for members already aligned.
 * Pure and page-space in/out: the caller (inspector wiring) is responsible
 * for converting each returned box into the node's own commit shape
 * (absolute_box for a pinned node, parent-rebased transform for a free-
 * context child) exactly the way a drag commit does.
 */
export function computeAlignTargets(
  items: AlignDistributeItem[],
  mode: AlignMode
): AlignDistributeTarget[] {
  if (items.length < 2) {
    return [];
  }
  const union = unionBox(items);
  const targets: AlignDistributeTarget[] = [];
  for (const item of items) {
    let nextX = item.box.x;
    let nextY = item.box.y;
    switch (mode) {
      case "left":
        nextX = union.x;
        break;
      case "center-h":
        nextX = union.x + union.width / 2 - item.box.width / 2;
        break;
      case "right":
        nextX = union.x + union.width - item.box.width;
        break;
      case "top":
        nextY = union.y;
        break;
      case "middle-v":
        nextY = union.y + union.height / 2 - item.box.height / 2;
        break;
      case "bottom":
        nextY = union.y + union.height - item.box.height;
        break;
    }
    if (nextX !== item.box.x || nextY !== item.box.y) {
      targets.push({ id: item.id, box: { ...item.box, x: nextX, y: nextY } });
    }
  }
  return targets;
}

/**
 * Distribute 3+ page-space boxes along an axis: sort by box center along the
 * axis, keep the first and last fixed, and space the remaining boxes so the
 * gaps between consecutive boxes (edge to edge, not center to center) are
 * equal. Sizes never change. Returns only the (always-middle) boxes whose
 * position changes.
 */
export function computeDistributeTargets(
  items: AlignDistributeItem[],
  axis: DistributeAxis
): AlignDistributeTarget[] {
  if (items.length < 3) {
    return [];
  }
  const dim: "x" | "y" = axis === "horizontal" ? "x" : "y";
  const size: "width" | "height" = axis === "horizontal" ? "width" : "height";

  const sorted = [...items].sort((left, right) => {
    const leftCenter = left.box[dim] + left.box[size] / 2;
    const rightCenter = right.box[dim] + right.box[size] / 2;
    return leftCenter - rightCenter;
  });

  const first = sorted[0];
  const last = sorted[sorted.length - 1];
  const span = last.box[dim] + last.box[size] - first.box[dim];
  const totalSize = sorted.reduce((sum, item) => sum + item.box[size], 0);
  const gapCount = sorted.length - 1;
  const gap = (span - totalSize) / gapCount;

  const targets: AlignDistributeTarget[] = [];
  let cursor = first.box[dim] + first.box[size] + gap;
  for (let i = 1; i < sorted.length - 1; i += 1) {
    const item = sorted[i];
    const nextPosition = cursor;
    if (nextPosition !== item.box[dim]) {
      const nextBox: Rect =
        axis === "horizontal"
          ? { ...item.box, x: nextPosition }
          : { ...item.box, y: nextPosition };
      targets.push({ id: item.id, box: nextBox });
    }
    cursor = nextPosition + item.box[size] + gap;
  }
  return targets;
}

/**
 * Converts one align/distribute target box into its `UpdateNode` commit —
 * mirroring the pinned/freehand branch of `canvasDragOperations` in
 * `canvasOperations.ts` (that module is owned by another concurrent agent,
 * so this replicates the minimal conversion rather than importing it):
 * a pinned node (`position_mode === "absolute"`) commits a page-space
 * `absolute_box`; a freehand child of a Free auto-layout container commits
 * a `transform` rebased into the parent's frame via `parentComputedOrigin`.
 * Sizes are carried through unchanged since align/distribute never resizes.
 * Returns null for a node that is neither (not direct-geometry-editable —
 * the caller pre-gates with `canAlignNodes`/`canDistributeNodes`, so this
 * is a defensive fallback, not the expected path).
 */
export function alignDistributeCommitOperation(scene: Scene, node: Node, box: Rect): Operation | null {
  if (node.position_mode === "absolute") {
    return updateNodeAbsoluteBox(node, {
      ...box,
      width: node.absolute_box?.width ?? box.width,
      height: node.absolute_box?.height ?? box.height
    });
  }
  if (isNodeFreehand(scene, node.id)) {
    const origin = parentComputedOrigin(scene, node.id);
    return updateNodeTransform(node, {
      ...node.transform,
      x: box.x - origin.x,
      y: box.y - origin.y
    });
  }
  return null;
}

/** One atomic batch: reads every selected node's current page-space box,
 * computes the align targets, and converts each changed target into its
 * commit operation — ready for a single `applyOperations(ops)` call (one
 * undo frame, matching a multi-node drag commit). Nodes with no resolvable
 * box (never laid out) are skipped defensively; the caller pre-gates
 * eligibility with `canAlignNodes`. */
export function alignNodesOperations(scene: Scene, nodeIds: NodeId[], mode: AlignMode): Operation[] {
  const items = readBoxes(scene, nodeIds);
  const targets = computeAlignTargets(items, mode);
  return commitTargets(scene, targets);
}

/** Same shape as `alignNodesOperations`, for Distribute. */
export function distributeNodesOperations(scene: Scene, nodeIds: NodeId[], axis: DistributeAxis): Operation[] {
  const items = readBoxes(scene, nodeIds);
  const targets = computeDistributeTargets(items, axis);
  return commitTargets(scene, targets);
}

function readBoxes(scene: Scene, nodeIds: NodeId[]): AlignDistributeItem[] {
  const items: AlignDistributeItem[] = [];
  for (const id of nodeIds) {
    const box = nodePageSpaceBox(scene, id);
    if (box) {
      items.push({ id, box });
    }
  }
  return items;
}

function commitTargets(scene: Scene, targets: AlignDistributeTarget[]): Operation[] {
  const operations: Operation[] = [];
  for (const target of targets) {
    const node = scene.nodes[target.id];
    if (!node) {
      continue;
    }
    const operation = alignDistributeCommitOperation(scene, node, target.box);
    if (operation) {
      operations.push(operation);
    }
  }
  return operations;
}
