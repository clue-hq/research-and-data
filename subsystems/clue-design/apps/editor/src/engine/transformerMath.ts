/**
 * Wave 3 C3c: the resize/rotate transformer math.
 *
 * Konva's retained-mode `Transformer` computed handle geometry for us;
 * CanvasKit is immediate-mode, so the interaction layer must do it itself.
 * These are pure functions over canvas-space geometry — no renderer, no
 * scene — so they are exhaustively unit-testable and feed the EXISTING
 * `canvasResizeOperation` (the gesture layer converts the returned box to
 * scale factors). Resizing anchors the opposite corner/edge, honors a
 * minimum size, optional aspect lock (corner handles), and rotation: the
 * box is resized in its LOCAL (unrotated) frame so the anchor stays
 * visually fixed while the box is rotated about its top-left origin (the
 * pivot the renderer and hit-testing use).
 */

export interface Point {
  x: number;
  y: number;
}

export interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

export type ResizeHandle =
  | "top-left"
  | "top"
  | "top-right"
  | "right"
  | "bottom-right"
  | "bottom"
  | "bottom-left"
  | "left";

export interface ResizeOptions {
  /** Minimum width/height (canvas units). Default 2. */
  minWidth?: number;
  minHeight?: number;
  /** Preserve the original aspect ratio (Shift). Corner handles only. */
  aspectLocked?: boolean;
  /** The box's rotation in degrees, about its top-left origin. Default 0. */
  rotation?: number;
}

const DEFAULT_MIN = 2;

/** Rotate `p` by `deg` degrees about the origin (y-down, clockwise-positive).
 * `+rotation` maps a box-local vector to world; `-rotation` maps world→local. */
export function rotatePoint(p: Point, deg: number): Point {
  if (deg === 0) {
    return { x: p.x, y: p.y };
  }
  const r = (deg * Math.PI) / 180;
  const c = Math.cos(r);
  const s = Math.sin(r);
  return { x: p.x * c - p.y * s, y: p.x * s + p.y * c };
}

/**
 * The new box after dragging `handle` to `pointer` (canvas space). The
 * opposite corner/edge stays fixed in world space; the result keeps the box's
 * rotation. Width/height never fall below the minimum (the dragged edge is
 * clamped, the anchor never moves). With `aspectLocked` a corner drag keeps
 * the original ratio.
 */
export function resizeBox(
  box: Box,
  handle: ResizeHandle,
  pointer: Point,
  options: ResizeOptions = {}
): Box {
  const rotation = options.rotation ?? 0;
  const minW = Math.max(options.minWidth ?? DEFAULT_MIN, 0);
  const minH = Math.max(options.minHeight ?? DEFAULT_MIN, 0);
  const origin: Point = { x: box.x, y: box.y };

  // Pointer in the box's local, unrotated frame (origin at the box top-left).
  const local = rotatePoint({ x: pointer.x - origin.x, y: pointer.y - origin.y }, -rotation);

  const movesLeft = handle.includes("left");
  const movesRight = handle.includes("right");
  const movesTop = handle.includes("top");
  const movesBottom = handle.includes("bottom");

  let x0 = 0;
  let y0 = 0;
  let x1 = box.width;
  let y1 = box.height;
  if (movesLeft) x0 = local.x;
  if (movesRight) x1 = local.x;
  if (movesTop) y0 = local.y;
  if (movesBottom) y1 = local.y;

  // Enforce the minimum by clamping the DRAGGED edge; the anchor edge never
  // moves, and the box never flips (V0: no negative size).
  if (movesLeft) x0 = Math.min(x0, x1 - minW);
  if (movesRight) x1 = Math.max(x1, x0 + minW);
  if (movesTop) y0 = Math.min(y0, y1 - minH);
  if (movesBottom) y1 = Math.max(y1, y0 + minH);

  // Aspect lock applies to corner handles (both axes move).
  if (options.aspectLocked && (movesLeft || movesRight) && (movesTop || movesBottom) && box.height !== 0) {
    const ratio = box.width / box.height;
    let w = x1 - x0;
    let h = y1 - y0;
    if (Math.abs(w - box.width) >= Math.abs(h - box.height)) {
      h = w / ratio;
    } else {
      w = h * ratio;
    }
    // Re-anchor toward the fixed corner.
    if (movesLeft) {
      x0 = x1 - w;
    } else {
      x1 = x0 + w;
    }
    if (movesTop) {
      y0 = y1 - h;
    } else {
      y1 = y0 + h;
    }
  }

  const width = x1 - x0;
  const height = y1 - y0;
  // The new local top-left (x0,y0) maps back to world through the rotation,
  // keeping the anchor corner exactly where it was.
  const worldTopLeft = rotatePoint({ x: x0, y: y0 }, rotation);
  return {
    x: origin.x + worldTopLeft.x,
    y: origin.y + worldTopLeft.y,
    width,
    height
  };
}

/** Angle (degrees) from `pivot` to `pointer`, y-down. The rotate gesture takes
 * the delta from the angle at grab time. */
export function angleFromPivot(pivot: Point, pointer: Point): number {
  return (Math.atan2(pointer.y - pivot.y, pointer.x - pivot.x) * 180) / Math.PI;
}

/** Snap `deg` to the nearest multiple of `step` (e.g. 15° with Shift). */
export function snapAngle(deg: number, step: number): number {
  if (!step) {
    return deg;
  }
  return Math.round(deg / step) * step;
}

/** Normalize a degree value into [0, 360). */
export function normalizeAngle(deg: number): number {
  const m = deg % 360;
  return m < 0 ? m + 360 : m;
}

/** The world-space position of a resize handle on a (possibly rotated) box —
 * used by the overlay to place handles and by the gesture layer to hit them. */
export function handlePoint(box: Box, handle: ResizeHandle, rotation = 0): Point {
  const lx = handle.includes("left") ? 0 : handle.includes("right") ? box.width : box.width / 2;
  const ly = handle.includes("top") ? 0 : handle.includes("bottom") ? box.height : box.height / 2;
  const world = rotatePoint({ x: lx, y: ly }, rotation);
  return { x: box.x + world.x, y: box.y + world.y };
}
