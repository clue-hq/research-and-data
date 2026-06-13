/**
 * Wave 3 C3b/host: the pure glue between pointer events and the gesture
 * machine for the CanvasKit canvas. Coordinate conversions and handle
 * detection live here (testable); the React host (`CanvasKitCanvas`) is thin
 * DOM wiring over these plus `gestureReducer` and the EXISTING operation
 * builders.
 *
 * Three spaces:
 * - screen px: raw pointer offset within the canvas element.
 * - descriptor space: canvas px at zoom 1 (= computed × unitScale). The
 *   gesture machine, transformer math, and overlay all work here.
 * - scene units: the engine's `computed` coordinates (descriptor ÷ unitScale).
 *   `engine.hitTest` takes these.
 */

import type { Node as SceneNodeModel, Operation, Page, Scene } from "./contracts";
import { canvasDragOperation, canvasResizeOperation } from "./canvasOperations";
import { nodeSizeForRender } from "./renderAdapter";
import { handlePoint, type Box, type Point, type ResizeHandle } from "./transformerMath";

/** Distance (screen px) within which a press counts as grabbing a handle. */
export const HANDLE_HIT_RADIUS = 7;

export const RESIZE_HANDLES: ResizeHandle[] = [
  "top-left",
  "top",
  "top-right",
  "right",
  "bottom-right",
  "bottom",
  "bottom-left",
  "left"
];

const ROTATE_OFFSET = 22;

export function screenToDescriptor(point: Point, pageOrigin: Point, zoom: number): Point {
  return { x: (point.x - pageOrigin.x) / zoom, y: (point.y - pageOrigin.y) / zoom };
}

export function descriptorToScene(point: Point, unitScale: number): Point {
  return { x: point.x / unitScale, y: point.y / unitScale };
}

/**
 * Which resize/rotate handle (if any) the descriptor-space point is grabbing,
 * given the selection box. Returns the handle, "rotate", or null. The radius
 * is in screen px, scaled to descriptor space by `zoom`.
 */
export function handleAtPoint(
  point: Point,
  box: Box,
  rotation: number,
  zoom: number,
  radius = HANDLE_HIT_RADIUS
): ResizeHandle | "rotate" | null {
  const tol = radius / zoom;

  const rad = (rotation * Math.PI) / 180;
  const top = handlePoint(box, "top", rotation);
  const rotateHandle = { x: top.x + Math.sin(rad) * ROTATE_OFFSET, y: top.y - Math.cos(rad) * ROTATE_OFFSET };
  if (within(point, rotateHandle, tol)) {
    return "rotate";
  }

  let best: { handle: ResizeHandle; d: number } | null = null;
  for (const handle of RESIZE_HANDLES) {
    const p = handlePoint(box, handle, rotation);
    const d = distance(point, p);
    if (d <= tol && (!best || d < best.d)) {
      best = { handle, d };
    }
  }
  return best?.handle ?? null;
}

/** Convert a drag action's descriptor-space box into a canonical operation. */
export function dragActionToOperation(
  box: Box,
  scene: Scene,
  node: SceneNodeModel,
  page: Page,
  pageOrigin: Point
): Operation | null {
  return canvasDragOperation({
    scene,
    node,
    page,
    pageOrigin,
    // canvasDragOperation subtracts pageOrigin then converts to scene units;
    // the descriptor box top-left lives in unscaled stage space at pageOrigin.
    canvasX: pageOrigin.x + box.x,
    canvasY: pageOrigin.y + box.y
  });
}

/** Convert a resize action's descriptor-space box into a canonical operation,
 * expressing the new size as scale factors over the node's base render size. */
export function resizeActionToOperation(
  box: Box,
  rotation: number,
  scene: Scene,
  node: SceneNodeModel,
  page: Page,
  pageOrigin: Point
): Operation | null {
  const base = nodeSizeForRender(node, page);
  if (base.width === 0 || base.height === 0) {
    return null;
  }
  return canvasResizeOperation({
    scene,
    node,
    page,
    pageOrigin,
    transform: {
      canvasX: pageOrigin.x + box.x,
      canvasY: pageOrigin.y + box.y,
      rotation,
      scaleX: box.width / base.width,
      scaleY: box.height / base.height
    }
  });
}

function within(a: Point, b: Point, tol: number): boolean {
  return distance(a, b) <= tol;
}

function distance(a: Point, b: Point): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}
