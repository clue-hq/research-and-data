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

/** Smart-guide style — Moda's focus-blue (`--color-border-focus` /
 * `--color-accent-blue`), dashed so a guide reads as a transient snap signal
 * rather than persistent selection chrome. One constant, shared by both
 * canvas paths (`SelectionOverlay` for CanvasKit, `SnapGuideLayer` for the
 * Konva fallback) so they render guides identically. */
export const SNAP_GUIDE_COLOR = "#4c8dff";
export const SNAP_GUIDE_DASH: [number, number] = [4, 3];

export interface CanvasPoint {
  x: number;
  y: number;
}

/** One active snap guide, in page space (scene units). `position` is the
 * snapped edge/center line; `from`/`to` span the full page extent along the
 * guide (entire width for a "y" guide's x-run, entire height for an "x"
 * guide's y-run) — Moda-style full-bleed guide lines, not just the dragged
 * box's extent, computed here (where page size is in scope) so both
 * renderers inherit it verbatim. */
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
  // Moda-style) — but it DOES snap to page guides, same as a managed node's
  // transform: post-Phase-1, Absolute nodes are exactly what humans drag,
  // and Moda snaps everything.
  const pin = pinnedBox(node);
  if (pin) {
    const snappedPosition = snapPinnedPositionToGuides({
      page,
      box: { x: pageX, y: pageY, width: pin.width, height: pin.height }
    });
    const nextBox = {
      ...pin,
      x: roundForOperation(snappedPosition.x),
      y: roundForOperation(snappedPosition.y)
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
  // no clamp — same freehand policy as pinned nodes. Snaps against page
  // guides too (4c): rebuild the page-space candidate box from the parent's
  // solved origin (the same source the rebase below reads) plus the live
  // drag position, snap that box exactly like a pinned node, then rebase the
  // snapped page-space position back to parent space before committing.
  if (isNodeFreehand(scene, node.id)) {
    const origin = parentComputedOrigin(scene, node.id);
    const size = nodeSceneUnitSize(node, page);
    const snappedPosition = snapPinnedPositionToGuides({
      page,
      box: { x: pageX, y: pageY, width: size.width, height: size.height }
    });
    const nextTransform = {
      ...node.transform,
      x: roundForOperation(snappedPosition.x - origin.x),
      y: roundForOperation(snappedPosition.y - origin.y)
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
 * lines. Pinned (Absolute) nodes and freehand children of a Free container
 * both snap to page guides same as managed nodes (see
 * `canvasDragOperations`). Empty when no guide is within threshold. Never
 * mutates and never affects the committed operation. */
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
  const pageX = sceneUnitFromCanvas(canvasX - pageOrigin.x, page);
  const pageY = sceneUnitFromCanvas(canvasY - pageOrigin.y, page);
  const guides: SnapGuide[] = [];

  const pin = pinnedBox(node);
  if (pin) {
    snapPinnedPositionToGuides(
      { page, box: { x: pageX, y: pageY, width: pin.width, height: pin.height } },
      (guide) => guides.push(guide)
    );
    return guides;
  }

  // Freehand child of a Free container: snaps against page guides too (4c;
  // see canvasDragOperations) — page-space candidate box from the parent's
  // solved origin plus the live drag position, same as the committed path.
  if (isNodeFreehand(scene, node.id)) {
    const size = nodeSceneUnitSize(node, page);
    snapPinnedPositionToGuides(
      { page, box: { x: pageX, y: pageY, width: size.width, height: size.height } },
      (guide) => guides.push(guide)
    );
    return guides;
  }

  const rawTransform = { ...node.transform, x: pageX, y: pageY };
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
  // freehand policy, matching drags — but the box DOES snap to page guides,
  // consistent with drag's pinned-node snapping.
  if (pinnedBox(node)) {
    const snappedBox = snapPinnedBoxToGuides({
      page,
      box: {
        x: sceneUnitFromCanvas(transform.canvasX - pageOrigin.x, page),
        y: sceneUnitFromCanvas(transform.canvasY - pageOrigin.y, page),
        width: sceneUnitFromCanvas(nextWidth, page),
        height: sceneUnitFromCanvas(nextHeight, page)
      }
    });
    return updateNodeAbsoluteBoxAndRotation(
      node,
      {
        x: roundForOperation(snappedBox.x),
        y: roundForOperation(snappedBox.y),
        width: roundForOperation(snappedBox.width),
        height: roundForOperation(snappedBox.height)
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

  // Child of a Free container: parent-relative transform, no clamps. Snaps
  // against page guides too (4c): `nextTransform`/`rawSize` above are already
  // the page-space candidate box (built from `pageOrigin`, the canvas→page
  // origin — not the parent's origin), so snap it exactly like a pinned
  // node's resize, then rebase the snapped page-space position back to
  // parent space using the same `parentComputedOrigin` the commit already
  // reads.
  if (isNodeFreehand(scene, node.id)) {
    const origin = parentComputedOrigin(scene, node.id);
    const snappedBox = snapPinnedBoxToGuides({
      page,
      box: { x: nextTransform.x, y: nextTransform.y, width: rawSize.width, height: rawSize.height }
    });
    return updateNodeTransformAndSize(
      node,
      {
        ...nextTransform,
        x: roundForOperation(snappedBox.x - origin.x),
        y: roundForOperation(snappedBox.y - origin.y)
      },
      {
        width: { kind: "fixed", value: roundForOperation(snappedBox.width) },
        height: { kind: "fixed", value: roundForOperation(snappedBox.height) }
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
 * lines. Pinned (Absolute) nodes and freehand children of a Free container
 * both snap to page guides same as managed nodes (see
 * `canvasResizeOperation`). Empty when nothing is within threshold. */
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
  const baseSize = nodeSizeForRender(node, page);
  const nextWidth = Math.max(2, baseSize.width * Math.abs(transform.scaleX));
  const nextHeight = Math.max(2, baseSize.height * Math.abs(transform.scaleY));
  const guides: SnapGuide[] = [];

  // Pinned (Absolute) nodes and freehand children of a Free container share
  // the same page-space candidate box here — `transform.canvasX/canvasY`
  // relative to `pageOrigin` (canvas→page origin) is page space regardless
  // of which case it is; only the commit path (canvasResizeOperation) later
  // rebases a freehand node's snapped box into its parent's frame.
  if (pinnedBox(node) || isNodeFreehand(scene, node.id)) {
    snapPinnedBoxToGuides(
      {
        page,
        box: {
          x: sceneUnitFromCanvas(transform.canvasX - pageOrigin.x, page),
          y: sceneUnitFromCanvas(transform.canvasY - pageOrigin.y, page),
          width: sceneUnitFromCanvas(nextWidth, page),
          height: sceneUnitFromCanvas(nextHeight, page)
        }
      },
      (guide) => guides.push(guide)
    );
    return guides;
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
  const nextX = snapAxis("x", transform.x, size.width, guides.x, threshold, true, page, onGuide);
  const nextY = snapAxis("y", transform.y, size.height, guides.y, threshold, true, page, onGuide);
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
    page,
    onGuide
  );
  snapped.transform.y = snapAxis(
    "y",
    snapped.transform.y,
    snapped.size.height,
    guides.y,
    threshold,
    false,
    page,
    onGuide
  );
  snapped.size.width = snapExtentAxis("x", snapped.transform.x, snapped.size.width, guides.x, threshold, page, onGuide);
  snapped.size.height = snapExtentAxis(
    "y",
    snapped.transform.y,
    snapped.size.height,
    guides.y,
    threshold,
    page,
    onGuide
  );
  return snapped;
}

/** Snaps a pinned (Absolute) node's page-space box position to the page's
 * guide targets (bounds / safe-area edges / midlines) — the pinned
 * counterpart to `snapTransformToGuides`. Absolute nodes are exactly what
 * humans drag post-Phase-1, and Moda snaps everything; there is no reason a
 * freehand-placed node should be exempt from the same 8px-threshold guides
 * as a flow node. Position only (size unaffected) — matches drag semantics
 * for managed nodes. */
function snapPinnedPositionToGuides(
  { page, box }: { page: Page; box: { x: number; y: number; width: number; height: number } },
  onGuide?: (guide: SnapGuide) => void
): { x: number; y: number } {
  const guides = guidesForPage(page);
  const threshold = sceneUnitFromCanvas(SNAP_THRESHOLD_CANVAS_PX, page);
  const nextX = snapAxis("x", box.x, box.width, guides.x, threshold, true, page, onGuide);
  const nextY = snapAxis("y", box.y, box.height, guides.y, threshold, true, page, onGuide);
  return { x: nextX, y: nextY };
}

/** Snaps a pinned (Absolute) node's page-space box position AND size to the
 * page's guide targets — the pinned counterpart to
 * `snapTransformAndSizeToGuides`, used by resize. */
function snapPinnedBoxToGuides(
  { page, box }: { page: Page; box: { x: number; y: number; width: number; height: number } },
  onGuide?: (guide: SnapGuide) => void
): { x: number; y: number; width: number; height: number } {
  const guides = guidesForPage(page);
  const threshold = sceneUnitFromCanvas(SNAP_THRESHOLD_CANVAS_PX, page);
  const snapped = { ...box };
  snapped.x = snapAxis("x", snapped.x, snapped.width, guides.x, threshold, false, page, onGuide);
  snapped.y = snapAxis("y", snapped.y, snapped.height, guides.y, threshold, false, page, onGuide);
  snapped.width = snapExtentAxis("x", snapped.x, snapped.width, guides.x, threshold, page, onGuide);
  snapped.height = snapExtentAxis("y", snapped.y, snapped.height, guides.y, threshold, page, onGuide);
  return snapped;
}

/** `snapPosition`, plus (when a snap engages) reporting the guide segment as
 * a line perpendicular to `axis`, spanning the ENTIRE artboard on the cross
 * axis — an "x" guide is a vertical line at the snapped x, drawn from y=0 to
 * the full page height (Moda-style full-bleed guide), not just the dragged
 * box's extent; the page is in scope here, so both renderers inherit the
 * span verbatim. `reportOtherEnd` extends the search to the trailing-edge
 * candidate too (drag: box may snap by either edge or center; resize: only
 * the leading edge moves). */
function snapAxis(
  axis: "x" | "y",
  position: number,
  extent: number,
  guides: number[],
  threshold: number,
  reportOtherEnd: boolean,
  page: Page,
  onGuide?: (guide: SnapGuide) => void
): number {
  const candidate = snapPositionWithCandidate(position, extent, guides, threshold, reportOtherEnd);
  if (!candidate) {
    return position;
  }
  if (onGuide) {
    const span = pageCrossAxisSpan(axis, page);
    onGuide({
      axis,
      position: roundForOperation(candidate.guide),
      from: span.from,
      to: span.to
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
  page: Page,
  onGuide?: (guide: SnapGuide) => void
): number {
  const candidate = snapExtentWithCandidate(position, extent, guides, threshold);
  if (!candidate) {
    return extent;
  }
  if (onGuide) {
    const span = pageCrossAxisSpan(axis, page);
    onGuide({
      axis,
      position: roundForOperation(candidate.guide),
      from: span.from,
      to: span.to
    });
  }
  return roundForOperation(candidate.value);
}

/** The full-artboard span a guide line is drawn across on its CROSS axis —
 * an "x" guide (vertical line) runs the page's full height; a "y" guide
 * (horizontal line) runs the page's full width. Always page-space [0, page
 * extent], regardless of the dragged node's own bounds. */
function pageCrossAxisSpan(axis: "x" | "y", page: Page): { from: number; to: number } {
  const extent = axis === "x" ? page.size.height : page.size.width;
  return { from: 0, to: roundForOperation(extent) };
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
    return guidesForPage(parentPage);
  }

  const parentNode = scene.nodes[parentInfo.parent.id];
  if (!parentNode) {
    return null;
  }
  const parentSize = nodeSceneUnitSize(parentNode, page);
  return dedupeGuides(guidesForBounds(parentSize.width, parentSize.height));
}

/** Page bounds + safe-area guide targets, in page space. A pinned
 * (Absolute) node's `absolute_box` is already page-space regardless of
 * structural nesting, so it always snaps against the PAGE — not whatever
 * container it happens to be a descendant of (unlike `guidesForNodeParent`,
 * which resolves the immediate structural parent's local frame for
 * flow-positioned nodes). */
function guidesForPage(page: Page): { x: number[]; y: number[] } {
  const guides = guidesForBounds(page.size.width, page.size.height);
  if (page.safe_area) {
    guides.x.push(
      page.safe_area.x,
      page.safe_area.x + page.safe_area.width,
      page.safe_area.x + page.safe_area.width / 2
    );
    guides.y.push(
      page.safe_area.y,
      page.safe_area.y + page.safe_area.height,
      page.safe_area.y + page.safe_area.height / 2
    );
  }
  return dedupeGuides(guides);
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
