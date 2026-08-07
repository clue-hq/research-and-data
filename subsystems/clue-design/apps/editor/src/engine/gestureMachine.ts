/**
 * Wave 3 C3b: the pointer→gesture state machine.
 *
 * Konva delegated events to nodes and ran drag/transform for us; CanvasKit is
 * immediate-mode, so the interaction layer drives gestures from raw pointer
 * events. This is a PURE reducer: `(state, event) → { state, action }`. The
 * host (the CanvasKit canvas) translates pointer events into `GestureEvent`s
 * — supplying the hit result and the selected box from the C3a hit-test and
 * the render geometry — and applies the returned `GestureAction` through the
 * EXISTING operation builders (`canvasDragOperation`, `canvasResizeOperation`).
 * No new mutation path; the W6 conformance gate still holds.
 *
 * Geometry is canvas space. Resizes use the C3c transformer math; drags
 * translate the box; rotation takes the angle delta from grab time. Boxes are
 * previewed live and committed on pointer-up only past a small threshold, so a
 * click selects without nudging.
 */

import type { NodeId } from "./contracts";
import {
  angleFromPivot,
  normalizeAngle,
  resizeBox,
  snapAngle,
  type Box,
  type Point,
  type ResizeHandle
} from "./transformerMath";

/** Movement (canvas px) before a press becomes a drag — a click stays a click. */
export const DRAG_THRESHOLD = 3;
/** Angle snap step (degrees) while rotating with Shift. */
export const ANGLE_SNAP_STEP = 15;

export interface Modifiers {
  /** Aspect lock on resize; angle snap on rotate. */
  shift?: boolean;
  /** Additive selection / deep click-through. */
  meta?: boolean;
}

/** What the pointer went down on, resolved by the host via hit-testing. */
export type PressTarget =
  | { kind: "node"; nodeId: NodeId; box: Box; rotation: number }
  | { kind: "handle"; nodeId: NodeId; handle: ResizeHandle; box: Box; rotation: number }
  | { kind: "rotate"; nodeId: NodeId; pivot: Point; box: Box; rotation: number }
  | { kind: "empty" };

export type GestureEvent =
  | { kind: "down"; point: Point; target: PressTarget; modifiers: Modifiers }
  | { kind: "move"; point: Point; modifiers: Modifiers }
  | { kind: "up"; point: Point; modifiers: Modifiers };

export type GestureState =
  | { kind: "idle" }
  | { kind: "pressed"; origin: Point; target: PressTarget; moved: boolean }
  | { kind: "dragging"; nodeId: NodeId; origin: Point; startBox: Box }
  | { kind: "resizing"; nodeId: NodeId; handle: ResizeHandle; startBox: Box; rotation: number }
  | { kind: "rotating"; nodeId: NodeId; pivot: Point; startAngle: number; startRotation: number }
  | { kind: "marquee"; origin: Point };

export type GestureAction =
  | { kind: "none" }
  | { kind: "select"; nodeId: NodeId | null; additive: boolean }
  | { kind: "drag"; nodeId: NodeId; box: Box; committed: boolean }
  | { kind: "resize"; nodeId: NodeId; box: Box; committed: boolean }
  | { kind: "rotate"; nodeId: NodeId; rotation: number; committed: boolean }
  | { kind: "marquee"; rect: Box; committed: boolean };

export const initialGestureState: GestureState = { kind: "idle" };

/** A reducer step: the next state plus the action the host should apply. */
export interface Reduced {
  state: GestureState;
  action: GestureAction;
}

export function gestureReducer(state: GestureState, event: GestureEvent): Reduced {
  switch (event.kind) {
    case "down":
      return onDown(event.point, event.target, event.modifiers);
    case "move":
      return onMove(state, event.point, event.modifiers);
    case "up":
      return onUp(state, event.point, event.modifiers);
  }
}

function onDown(point: Point, target: PressTarget, modifiers: Modifiers): Reduced {
  // Selecting happens on press (Figma-style): a node press selects it
  // immediately, an empty press clears selection unless additive.
  const additive = Boolean(modifiers.shift || modifiers.meta);
  let action: GestureAction = { kind: "none" };
  if (target.kind === "node") {
    action = { kind: "select", nodeId: target.nodeId, additive };
  } else if (target.kind === "empty" && !additive) {
    // An empty press clears the selection — unless an additive modifier is
    // held, in which case the multi-selection is preserved.
    action = { kind: "select", nodeId: null, additive: false };
  }
  return {
    state: { kind: "pressed", origin: point, target, moved: false },
    action
  };
}

function onMove(state: GestureState, point: Point, modifiers: Modifiers): Reduced {
  switch (state.kind) {
    case "pressed": {
      if (!state.moved && distance(state.origin, point) < DRAG_THRESHOLD) {
        return { state, action: { kind: "none" } };
      }
      // Threshold crossed: promote the press into the matching gesture.
      return beginGesture(state.target, state.origin, point, modifiers);
    }
    case "dragging":
      return { state, action: dragAction(state, point, false) };
    case "resizing":
      return { state, action: resizeAction(state, point, modifiers, false) };
    case "rotating":
      return { state, action: rotateAction(state, point, modifiers, false) };
    case "marquee":
      return { state, action: { kind: "marquee", rect: rectFrom(state.origin, point), committed: false } };
    default:
      return { state, action: { kind: "none" } };
  }
}

function onUp(state: GestureState, point: Point, modifiers: Modifiers): Reduced {
  let action: GestureAction = { kind: "none" };
  switch (state.kind) {
    case "dragging":
      action = dragAction(state, point, true);
      break;
    case "resizing":
      action = resizeAction(state, point, modifiers, true);
      break;
    case "rotating":
      action = rotateAction(state, point, modifiers, true);
      break;
    case "marquee":
      action = { kind: "marquee", rect: rectFrom(state.origin, point), committed: true };
      break;
    default:
      action = { kind: "none" };
  }
  return { state: { kind: "idle" }, action };
}

function beginGesture(target: PressTarget, origin: Point, point: Point, modifiers: Modifiers): Reduced {
  switch (target.kind) {
    case "node": {
      const next = { kind: "dragging" as const, nodeId: target.nodeId, origin, startBox: target.box };
      return { state: next, action: dragAction(next, point, false) };
    }
    case "handle": {
      const next = {
        kind: "resizing" as const,
        nodeId: target.nodeId,
        handle: target.handle,
        startBox: target.box,
        rotation: target.rotation
      };
      return { state: next, action: resizeAction(next, point, modifiers, false) };
    }
    case "rotate": {
      const next = {
        kind: "rotating" as const,
        nodeId: target.nodeId,
        pivot: target.pivot,
        startAngle: angleFromPivot(target.pivot, origin),
        startRotation: target.rotation
      };
      return { state: next, action: rotateAction(next, point, modifiers, false) };
    }
    case "empty": {
      const next = { kind: "marquee" as const, origin };
      return { state: next, action: { kind: "marquee", rect: rectFrom(origin, point), committed: false } };
    }
  }
}

function dragAction(
  state: Extract<GestureState, { kind: "dragging" }>,
  point: Point,
  committed: boolean
): GestureAction {
  const dx = point.x - state.origin.x;
  const dy = point.y - state.origin.y;
  return {
    kind: "drag",
    nodeId: state.nodeId,
    box: { ...state.startBox, x: state.startBox.x + dx, y: state.startBox.y + dy },
    committed
  };
}

function resizeAction(
  state: Extract<GestureState, { kind: "resizing" }>,
  point: Point,
  modifiers: Modifiers,
  committed: boolean
): GestureAction {
  const box = resizeBox(state.startBox, state.handle, point, {
    rotation: state.rotation,
    aspectLocked: Boolean(modifiers.shift)
  });
  return { kind: "resize", nodeId: state.nodeId, box, committed };
}

function rotateAction(
  state: Extract<GestureState, { kind: "rotating" }>,
  point: Point,
  modifiers: Modifiers,
  committed: boolean
): GestureAction {
  const delta = angleFromPivot(state.pivot, point) - state.startAngle;
  let rotation = state.startRotation + delta;
  if (modifiers.shift) {
    rotation = snapAngle(rotation, ANGLE_SNAP_STEP);
  }
  return { kind: "rotate", nodeId: state.nodeId, rotation: normalizeAngle(rotation), committed };
}

function distance(a: Point, b: Point): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function rectFrom(a: Point, b: Point): Box {
  return {
    x: Math.min(a.x, b.x),
    y: Math.min(a.y, b.y),
    width: Math.abs(a.x - b.x),
    height: Math.abs(a.y - b.y)
  };
}

/** Nodes whose box intersects the marquee rect (axis-aligned overlap test) —
 * the host passes each node's render box; selection takes the matches. */
export function marqueeSelection(rect: Box, boxes: Array<{ nodeId: NodeId; box: Box }>): NodeId[] {
  return boxes.filter(({ box }) => rectsIntersect(rect, box)).map(({ nodeId }) => nodeId);
}

function rectsIntersect(a: Box, b: Box): boolean {
  return (
    a.x < b.x + b.width &&
    a.x + a.width > b.x &&
    a.y < b.y + b.height &&
    a.y + a.height > b.y
  );
}
