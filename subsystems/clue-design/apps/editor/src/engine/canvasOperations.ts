import type { Node as SceneNodeModel, Operation, Page, Rect, Scene, Transform } from "./contracts";
import {
  updateNodeAbsoluteBox,
  updateNodeAbsoluteBoxAndRotation,
  updateNodeTransform,
  updateNodeTransformAndSize
} from "./operations";
import { nodeSizeForRender, sceneUnitFromCanvas } from "./renderAdapter";
import {
  clampNodeSizeToParentBounds,
  clampNodeTransformToParentBounds,
  isNodeDirectGeometryEditable,
  isNodeFreehand,
  parentComputedOrigin,
  parentInfoForNode
} from "./sceneQueries";

const SNAP_THRESHOLD_CANVAS_PX = 6;

export interface CanvasPoint {
  x: number;
  y: number;
}

/** One active snap guide, in page space (scene units). `position` is the
 * snapped edge/center line; `from`/`to` span both the dragged box and the
 * snap target along the guide, so the drawn line visually connects them. */
export interface SnapGuide {
  axis: "x" | "y";
  position: number;
  from: number;
  to: number;
}

export interface CanvasTransformInput {
  canvasX: number;
  canvasY: number;
  rotation: number;
  scaleX: number;
  scaleY: number;
}

/** Page-space box a pinned node currently lays out at (`absolute_box`,
 * falling back to solved geometry for a boxless pin). */
function pinnedBox(node: SceneNodeModel): Rect | null {
  if (node.position_mode !== "absolute") {
    return null;
  }
  return node.absolute_box ?? (node.computed ? { ...node.computed.layout_bounds } : null);
}

/** One drag commit, possibly multi-op: the primary geometry change plus —
 * when the dragged node is a container — one box translation per pinned
 * descendant, so "I moved the card" carries its pins along (containers
 * only; solver reflows never move a pin). All ops land in one batch, one
 * undo frame. */
export function canvasDragOperations({
  scene,
  node,
  page,
  pageOrigin,
  canvasX,
  canvasY
}: {
  scene: Scene;
  node: SceneNodeModel;
  page: Page;
  pageOrigin: CanvasPoint;
  canvasX: number;
  canvasY: number;
}): Operation[] {
  if (!isNodeDirectGeometryEditable(scene, node.id) || !Number.isFinite(canvasX) || !Number.isFinite(canvasY)) {
    return [];
  }

  const pageX = sceneUnitFromCanvas(canvasX - pageOrigin.x, page);
  const pageY = sceneUnitFromCanvas(canvasY - pageOrigin.y, page);

  // Pinned node: the drag rewrites the page-space box. No parent-bounds
  // clamp (freehand drags are honored past boundaries and the render clips,
  // Moda-style) and no guide snapping in v1 — the hand stays in control.
  const pin = pinnedBox(node);
  if (pin) {
    const nextBox = {
      ...pin,
      x: roundForOperation(pageX),
      y: roundForOperation(pageY)
    };
    return [
      updateNodeAbsoluteBox(node, nextBox),
      ...translatePinnedDescendants(scene, node, {
        x: nextBox.x - pin.x,
        y: nextBox.y - pin.y
      })
    ];
  }

  // Child of a Free container: hand-placed transform in the parent's frame;
  // no clamp — same freehand policy as pinned nodes.
  if (isNodeFreehand(scene, node.id)) {
    const origin = parentComputedOrigin(scene, node.id);
    const nextTransform = {
      ...node.transform,
      x: roundForOperation(pageX - origin.x),
      y: roundForOperation(pageY - origin.y)
    };
    return [
      updateNodeTransform(node, nextTransform),
      ...translatePinnedDescendants(scene, node, {
        x: nextTransform.x - node.transform.x,
        y: nextTransform.y - node.transform.y
      })
    ];
  }

  const rawTransform = {
    ...node.transform,
    x: pageX,
    y: pageY
  };
  const nextTransform = clampNodeTransformToParentBounds(
    scene,
    node,
    snapTransformToGuides({
      scene,
      node,
      page,
      transform: rawTransform,
      size: nodeSceneUnitSize(node, page)
    })
  );
  return [
    updateNodeTransform(node, nextTransform),
    ...translatePinnedDescendants(scene, node, {
      x: nextTransform.x - node.transform.x,
      y: nextTransform.y - node.transform.y
    })
  ];
}

export function canvasDragOperation(args: {
  scene: Scene;
  node: SceneNodeModel;
  page: Page;
  pageOrigin: CanvasPoint;
  canvasX: number;
  canvasY: number;
}): Operation | null {
  return canvasDragOperations(args)[0] ?? null;
}

/** The snap guides that would engage for this drag, in page space — a pure
 * readout alongside `canvasDragOperations` for the host to render as guide
 * lines. Empty when the node isn't guide-snapped (pinned/freehand nodes
 * don't snap, matching `canvasDragOperations`) or no guide is within
 * threshold. Never mutates and never affects the committed operation. */
export function dragSnapGuides({
  scene,
  node,
  page,
  pageOrigin,
  canvasX,
  canvasY
}: {
  scene: Scene;
  node: SceneNodeModel;
  page: Page;
  pageOrigin: CanvasPoint;
  canvasX: number;
  canvasY: number;
}): SnapGuide[] {
  if (!isNodeDirectGeometryEditable(scene, node.id) || !Number.isFinite(canvasX) || !Number.isFinite(canvasY)) {
    return [];
  }
  // Pinned and freehand drags don't snap (see canvasDragOperations) — no guides.
  if (pinnedBox(node) || isNodeFreehand(scene, node.id)) {
    return [];
  }
  const pageX = sceneUnitFromCanvas(canvasX - pageOrigin.x, page);
  const pageY = sceneUnitFromCanvas(canvasY - pageOrigin.y, page);
  const rawTransform = { ...node.transform, x: pageX, y: pageY };
  const guides: SnapGuide[] = [];
  snapTransformToGuides(
    {
      scene,
      node,
      page,
      transform: rawTransform,
      size: nodeSceneUnitSize(node, page)
    },
    (guide) => guides.push(guide)
  );
  return guides;
}

/** A translated container carries every pinned descendant's page-space box
 * by the same delta — the explicit-gesture half of the Phase 1d decision
 * (solver/agent reflows leave pins alone; a human moving the container
 * keeps the composition together). */
function translatePinnedDescendants(
  scene: Scene,
  node: SceneNodeModel,
  delta: { x: number; y: number }
): Operation[] {
  if (delta.x === 0 && delta.y === 0) {
    return [];
  }
  const operations: Operation[] = [];
  const walk = (nodeId: string) => {
    const child = scene.nodes[nodeId];
    if (!child) {
      return;
    }
    const pin = pinnedBox(child);
    if (pin) {
      operations.push(
        updateNodeAbsoluteBox(child, {
          ...pin,
          x: roundForOperation(pin.x + delta.x),
          y: roundForOperation(pin.y + delta.y)
        })
      );
    }
    child.children.forEach(walk);
  };
  node.children.forEach(walk);
  return operations;
}

export function canvasResizeOperation({
  scene,
  node,
  page,
  pageOrigin,
  transform
}: {
  scene: Scene;
  node: SceneNodeModel;
  page: Page;
  pageOrigin: CanvasPoint;
  transform: CanvasTransformInput;
}): Operation | null {
  if (!isNodeDirectGeometryEditable(scene, node.id) || !validCanvasTransform(transform)) {
    return null;
  }

  const baseSize = nodeSizeForRender(node, page);
  const nextWidth = Math.max(2, baseSize.width * Math.abs(transform.scaleX));
  const nextHeight = Math.max(2, baseSize.height * Math.abs(transform.scaleY));

  // Pinned node: resize rewrites the page-space box (and bakes the Fixed
  // size in the same patch); rotation rides the transform. No clamps —
  // freehand policy, matching drags.
  if (pinnedBox(node)) {
    return updateNodeAbsoluteBoxAndRotation(
      node,
      {
        x: roundForOperation(sceneUnitFromCanvas(transform.canvasX - pageOrigin.x, page)),
        y: roundForOperation(sceneUnitFromCanvas(transform.canvasY - pageOrigin.y, page)),
        width: roundForOperation(sceneUnitFromCanvas(nextWidth, page)),
        height: roundForOperation(sceneUnitFromCanvas(nextHeight, page))
      },
      transform.rotation
    );
  }

  const nextTransform: Transform = {
    ...node.transform,
    x: sceneUnitFromCanvas(transform.canvasX - pageOrigin.x, page),
    y: sceneUnitFromCanvas(transform.canvasY - pageOrigin.y, page),
    rotation: transform.rotation
  };
  const rawSize = {
    width: sceneUnitFromCanvas(nextWidth, page),
    height: sceneUnitFromCanvas(nextHeight, page)
  };

  // Child of a Free container: parent-relative transform, no clamps.
  if (isNodeFreehand(scene, node.id)) {
    const origin = parentComputedOrigin(scene, node.id);
    return updateNodeTransformAndSize(
      node,
      {
        ...nextTransform,
        x: roundForOperation(nextTransform.x - origin.x),
        y: roundForOperation(nextTransform.y - origin.y)
      },
      {
        width: { kind: "fixed", value: roundForOperation(rawSize.width) },
        height: { kind: "fixed", value: roundForOperation(rawSize.height) }
      }
    );
  }
  const snapped = snapTransformAndSizeToGuides({
    scene,
    node,
    page,
    transform: nextTransform,
    size: rawSize
  });
  const nextSize = clampNodeSizeToParentBounds(scene, node, snapped.size);
  const clampedTransform = clampNodeTransformToParentBounds(scene, node, snapped.transform, nextSize);

  return updateNodeTransformAndSize(node, clampedTransform, {
    width: {
      kind: "fixed",
      value: nextSize.width
    },
    height: {
      kind: "fixed",
      value: nextSize.height
    }
  });
}

/** The snap guides that would engage for this resize, in page space — a pure
 * readout alongside `canvasResizeOperation` for the host to render as guide
 * lines. Empty for pinned/freehand nodes (no guide snapping, matching
 * `canvasResizeOperation`) or when nothing is within threshold. */
export function resizeSnapGuides({
  scene,
  node,
  page,
  pageOrigin,
  transform
}: {
  scene: Scene;
  node: SceneNodeModel;
  page: Page;
  pageOrigin: CanvasPoint;
  transform: CanvasTransformInput;
}): SnapGuide[] {
  if (!isNodeDirectGeometryEditable(scene, node.id) || !validCanvasTransform(transform)) {
    return [];
  }
  if (pinnedBox(node) || isNodeFreehand(scene, node.id)) {
    return [];
  }
  const baseSize = nodeSizeForRender(node, page);
  const nextWidth = Math.max(2, baseSize.width * Math.abs(transform.scaleX));
  const nextHeight = Math.max(2, baseSize.height * Math.abs(transform.scaleY));
  const nextTransform: Transform = {
    ...node.transform,
    x: sceneUnitFromCanvas(transform.canvasX - pageOrigin.x, page),
    y: sceneUnitFromCanvas(transform.canvasY - pageOrigin.y, page),
    rotation: transform.rotation
  };
  const rawSize = {
    width: sceneUnitFromCanvas(nextWidth, page),
    height: sceneUnitFromCanvas(nextHeight, page)
  };
  const guides: SnapGuide[] = [];
  snapTransformAndSizeToGuides(
    {
      scene,
      node,
      page,
      transform: nextTransform,
      size: rawSize
    },
    (guide) => guides.push(guide)
  );
  return guides;
}

function validCanvasTransform(transform: CanvasTransformInput): boolean {
  return (
    Number.isFinite(transform.canvasX) &&
    Number.isFinite(transform.canvasY) &&
    Number.isFinite(transform.rotation) &&
    Number.isFinite(transform.scaleX) &&
    Number.isFinite(transform.scaleY) &&
    transform.scaleX !== 0 &&
    transform.scaleY !== 0
  );
}

function snapTransformToGuides(
  {
    scene,
    node,
    page,
    transform,
    size
  }: {
    scene: Scene;
    node: SceneNodeModel;
    page: Page;
    transform: Transform;
    size: { width: number; height: number };
  },
  onGuide?: (guide: SnapGuide) => void
): Transform {
  const guides = guidesForNodeParent(scene, node, page);
  if (!guides) {
    return transform;
  }
  const threshold = sceneUnitFromCanvas(SNAP_THRESHOLD_CANVAS_PX, page);
  const nextX = snapAxis("x", transform.x, size.width, guides.x, threshold, true, transform.y, size.height, onGuide);
  const nextY = snapAxis("y", transform.y, size.height, guides.y, threshold, true, transform.x, size.width, onGuide);
  return {
    ...transform,
    x: nextX,
    y: nextY
  };
}

function snapTransformAndSizeToGuides(
  {
    scene,
    node,
    page,
    transform,
    size
  }: {
    scene: Scene;
    node: SceneNodeModel;
    page: Page;
    transform: Transform;
    size: { width: number; height: number };
  },
  onGuide?: (guide: SnapGuide) => void
): { transform: Transform; size: { width: number; height: number } } {
  const guides = guidesForNodeParent(scene, node, page);
  if (!guides) {
    return {
      transform,
      size
    };
  }
  const threshold = sceneUnitFromCanvas(SNAP_THRESHOLD_CANVAS_PX, page);
  const snapped = {
    transform: { ...transform },
    size: { ...size }
  };
  snapped.transform.x = snapAxis(
    "x",
    snapped.transform.x,
    snapped.size.width,
    guides.x,
    threshold,
    false,
    snapped.transform.y,
    snapped.size.height,
    onGuide
  );
  snapped.transform.y = snapAxis(
    "y",
    snapped.transform.y,
    snapped.size.height,
    guides.y,
    threshold,
    false,
    snapped.transform.x,
    snapped.size.width,
    onGuide
  );
  snapped.size.width = snapExtentAxis(
    "x",
    snapped.transform.x,
    snapped.size.width,
    guides.x,
    threshold,
    snapped.transform.y,
    snapped.size.height,
    onGuide
  );
  snapped.size.height = snapExtentAxis(
    "y",
    snapped.transform.y,
    snapped.size.height,
    guides.y,
    threshold,
    snapped.transform.x,
    snapped.size.width,
    onGuide
  );
  return snapped;
}

/** `snapPosition`, plus (when a snap engages) reporting the guide segment as
 * a line perpendicular to `axis` — an "x" guide is a vertical line at the
 * snapped x, drawn across the box's extent on the CROSS axis (`crossStart`/
 * `crossExtent`), since the snap target here is a page-level line (page
 * bounds / safe-area edge or midline) with no independent box of its own to
 * connect to. `reportOtherEnd` extends the search to the trailing-edge
 * candidate too (drag: box may snap by either edge or center; resize: only
 * the leading edge moves). */
function snapAxis(
  axis: "x" | "y",
  position: number,
  extent: number,
  guides: number[],
  threshold: number,
  reportOtherEnd: boolean,
  crossStart: number,
  crossExtent: number,
  onGuide?: (guide: SnapGuide) => void
): number {
  const candidate = snapPositionWithCandidate(position, extent, guides, threshold, reportOtherEnd);
  if (!candidate) {
    return position;
  }
  if (onGuide) {
    onGuide({
      axis,
      position: roundForOperation(candidate.guide),
      from: roundForOperation(crossStart),
      to: roundForOperation(crossStart + crossExtent)
    });
  }
  return roundForOperation(candidate.value);
}

function snapExtentAxis(
  axis: "x" | "y",
  position: number,
  extent: number,
  guides: number[],
  threshold: number,
  crossStart: number,
  crossExtent: number,
  onGuide?: (guide: SnapGuide) => void
): number {
  const candidate = snapExtentWithCandidate(position, extent, guides, threshold);
  if (!candidate) {
    return extent;
  }
  if (onGuide) {
    onGuide({
      axis,
      position: roundForOperation(candidate.guide),
      from: roundForOperation(crossStart),
      to: roundForOperation(crossStart + crossExtent)
    });
  }
  return roundForOperation(candidate.value);
}

/** A snap candidate: `guide` is the page-space guide line it targets, `value`
 * is the resulting snapped position/extent, `distance` is how close the
 * unsnapped geometry came to it. */
interface SnapCandidate {
  distance: number;
  value: number;
  guide: number;
}

function snapPositionWithCandidate(
  position: number,
  extent: number,
  guides: number[],
  threshold: number,
  includeEnd = true
): SnapCandidate | null {
  const candidates: SnapCandidate[] = [];
  for (const guide of guides) {
    candidates.push({ distance: Math.abs(position - guide), value: guide, guide });
    candidates.push({ distance: Math.abs(position + extent / 2 - guide), value: guide - extent / 2, guide });
    if (includeEnd) {
      candidates.push({ distance: Math.abs(position + extent - guide), value: guide - extent, guide });
    }
  }
  const best = candidates.reduce<SnapCandidate | null>(
    (current, candidate) => (!current || candidate.distance < current.distance ? candidate : current),
    null
  );
  return best && best.distance <= threshold ? best : null;
}

function snapPosition(
  position: number,
  extent: number,
  guides: number[],
  threshold: number,
  includeEnd = true
): number {
  const candidate = snapPositionWithCandidate(position, extent, guides, threshold, includeEnd);
  return candidate ? roundForOperation(candidate.value) : position;
}

function snapExtentWithCandidate(
  position: number,
  extent: number,
  guides: number[],
  threshold: number
): SnapCandidate | null {
  const end = position + extent;
  let best: SnapCandidate | null = null;
  for (const guide of guides) {
    const value = guide - position;
    if (value <= 0) {
      continue;
    }
    const distance = Math.abs(end - guide);
    if (!best || distance < best.distance) {
      best = { distance, value, guide };
    }
  }
  return best && best.distance <= threshold ? best : null;
}

function snapExtent(position: number, extent: number, guides: number[], threshold: number): number {
  const candidate = snapExtentWithCandidate(position, extent, guides, threshold);
  return candidate ? roundForOperation(candidate.value) : extent;
}

function guidesForNodeParent(
  scene: Scene,
  node: SceneNodeModel,
  page: Page
): { x: number[]; y: number[] } | null {
  const parentInfo = parentInfoForNode(scene, node.id);
  if (!parentInfo) {
    return null;
  }

  if (parentInfo.parent.kind === "page") {
    const parentPage = scene.pages[parentInfo.parent.id];
    if (!parentPage) {
      return null;
    }
    const guides = guidesForBounds(parentPage.size.width, parentPage.size.height);
    if (parentPage.safe_area) {
      guides.x.push(parentPage.safe_area.x, parentPage.safe_area.x + parentPage.safe_area.width, parentPage.safe_area.x + parentPage.safe_area.width / 2);
      guides.y.push(parentPage.safe_area.y, parentPage.safe_area.y + parentPage.safe_area.height, parentPage.safe_area.y + parentPage.safe_area.height / 2);
    }
    return dedupeGuides(guides);
  }

  const parentNode = scene.nodes[parentInfo.parent.id];
  if (!parentNode) {
    return null;
  }
  const parentSize = nodeSceneUnitSize(parentNode, page);
  return dedupeGuides(guidesForBounds(parentSize.width, parentSize.height));
}

function nodeSceneUnitSize(node: SceneNodeModel, page: Page): { width: number; height: number } {
  const canvasSize = nodeSizeForRender(node, page);
  return {
    width: sceneUnitFromCanvas(canvasSize.width, page),
    height: sceneUnitFromCanvas(canvasSize.height, page)
  };
}

function guidesForBounds(width: number, height: number): { x: number[]; y: number[] } {
  return {
    x: [0, width / 2, width],
    y: [0, height / 2, height]
  };
}

function dedupeGuides(guides: { x: number[]; y: number[] }): { x: number[]; y: number[] } {
  return {
    x: [...new Set(guides.x.filter(Number.isFinite))],
    y: [...new Set(guides.y.filter(Number.isFinite))]
  };
}

function roundForOperation(value: number): number {
  return Math.round(value * 1000) / 1000;
}
