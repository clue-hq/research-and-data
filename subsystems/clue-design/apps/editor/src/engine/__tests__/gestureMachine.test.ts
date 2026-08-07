import { describe, expect, it } from "vitest";
import {
  DRAG_THRESHOLD,
  gestureReducer,
  initialGestureState,
  marqueeSelection,
  type GestureAction,
  type GestureEvent,
  type GestureState,
  type PressTarget
} from "../gestureMachine";
import type { Box } from "../transformerMath";

const NODE_BOX: Box = { x: 100, y: 100, width: 80, height: 40 };

function run(events: GestureEvent[]): { state: GestureState; actions: GestureAction[] } {
  let state = initialGestureState;
  const actions: GestureAction[] = [];
  for (const event of events) {
    const result = gestureReducer(state, event);
    state = result.state;
    actions.push(result.action);
  }
  return { state, actions };
}

const nodeTarget: PressTarget = { kind: "node", nodeId: "n1", box: NODE_BOX, rotation: 0 };

describe("gesture machine (Wave 3 C3b)", () => {
  it("selects a node on press and stays selected on a click (no drag)", () => {
    const { state, actions } = run([
      { kind: "down", point: { x: 120, y: 110 }, target: nodeTarget, modifiers: {} },
      { kind: "move", point: { x: 121, y: 110 }, modifiers: {} }, // within threshold
      { kind: "up", point: { x: 121, y: 110 }, modifiers: {} }
    ]);
    expect(actions[0]).toEqual({ kind: "select", nodeId: "n1", additive: false });
    expect(actions[1]).toEqual({ kind: "none" }); // below threshold → no drag
    expect(actions[2]).toEqual({ kind: "none" });
    expect(state.kind).toBe("idle");
  });

  it("meta-click selects additively", () => {
    const { actions } = run([
      { kind: "down", point: { x: 120, y: 110 }, target: nodeTarget, modifiers: { meta: true } }
    ]);
    expect(actions[0]).toEqual({ kind: "select", nodeId: "n1", additive: true });
  });

  it("shift-click selects additively (multi-select)", () => {
    const { actions } = run([
      { kind: "down", point: { x: 120, y: 110 }, target: nodeTarget, modifiers: { shift: true } }
    ]);
    expect(actions[0]).toEqual({ kind: "select", nodeId: "n1", additive: true });
  });

  it("clears selection on an empty press", () => {
    const { actions } = run([
      { kind: "down", point: { x: 5, y: 5 }, target: { kind: "empty" }, modifiers: {} }
    ]);
    expect(actions[0]).toEqual({ kind: "select", nodeId: null, additive: false });
  });

  it("keeps the multi-selection on a shift+empty press", () => {
    // Additive empty press must NOT clear — you're adding, not deselecting all.
    const { actions } = run([
      { kind: "down", point: { x: 5, y: 5 }, target: { kind: "empty" }, modifiers: { shift: true } }
    ]);
    expect(actions[0]).toEqual({ kind: "none" });
  });

  it("drags a node past the threshold and commits on release", () => {
    const { state, actions } = run([
      { kind: "down", point: { x: 120, y: 110 }, target: nodeTarget, modifiers: {} },
      { kind: "move", point: { x: 120 + DRAG_THRESHOLD + 7, y: 115 }, modifiers: {} },
      { kind: "up", point: { x: 140, y: 120 }, modifiers: {} }
    ]);
    // Live preview at the first over-threshold move.
    expect(actions[1]).toMatchObject({ kind: "drag", nodeId: "n1", committed: false });
    // Commit on up: the box translates by the pointer delta (20,10) from the
    // press point (120,110), so startBox (100,100) → (120,110).
    expect(actions[2]).toEqual({
      kind: "drag",
      nodeId: "n1",
      box: { x: 120, y: 110, width: 80, height: 40 },
      committed: true
    });
    expect(state.kind).toBe("idle");
  });

  it("resizes from a handle and commits", () => {
    const handleTarget: PressTarget = {
      kind: "handle",
      nodeId: "n1",
      handle: "bottom-right",
      box: { x: 0, y: 0, width: 100, height: 100 },
      rotation: 0
    };
    const { actions } = run([
      { kind: "down", point: { x: 100, y: 100 }, target: handleTarget, modifiers: {} },
      { kind: "move", point: { x: 160, y: 140 }, modifiers: {} },
      { kind: "up", point: { x: 160, y: 140 }, modifiers: {} }
    ]);
    expect(actions[2]).toEqual({
      kind: "resize",
      nodeId: "n1",
      box: { x: 0, y: 0, width: 160, height: 140 },
      committed: true
    });
  });

  it("aspect-locks a resize with Shift", () => {
    const handleTarget: PressTarget = {
      kind: "handle",
      nodeId: "n1",
      handle: "bottom-right",
      box: { x: 0, y: 0, width: 100, height: 50 },
      rotation: 0
    };
    const { actions } = run([
      { kind: "down", point: { x: 100, y: 50 }, target: handleTarget, modifiers: { shift: true } },
      { kind: "move", point: { x: 200, y: 60 }, modifiers: { shift: true } }
    ]);
    expect(actions[1]).toMatchObject({ kind: "resize", box: { width: 200, height: 100 } });
  });

  it("rotates about a pivot and snaps with Shift", () => {
    const rotateTarget: PressTarget = {
      kind: "rotate",
      nodeId: "n1",
      pivot: { x: 0, y: 0 },
      box: { x: 0, y: 0, width: 100, height: 100 },
      rotation: 0
    };
    // Grab straight up (angle 0 at the press point to the right), then drag.
    const { actions } = run([
      { kind: "down", point: { x: 100, y: 0 }, target: rotateTarget, modifiers: { shift: true } },
      { kind: "move", point: { x: 0, y: 100 }, modifiers: { shift: true } } // +90° from grab
    ]);
    expect(actions[1]).toMatchObject({ kind: "rotate", nodeId: "n1", rotation: 90, committed: false });
  });

  it("marquees from an empty press and commits the rect", () => {
    const { actions, state } = run([
      { kind: "down", point: { x: 10, y: 10 }, target: { kind: "empty" }, modifiers: {} },
      { kind: "move", point: { x: 50, y: 70 }, modifiers: {} },
      { kind: "up", point: { x: 50, y: 70 }, modifiers: {} }
    ]);
    expect(actions[2]).toEqual({
      kind: "marquee",
      rect: { x: 10, y: 10, width: 40, height: 60 },
      committed: true
    });
    expect(state.kind).toBe("idle");
  });
});

describe("marquee selection", () => {
  it("selects nodes whose box intersects the marquee", () => {
    const boxes = [
      { nodeId: "a", box: { x: 0, y: 0, width: 30, height: 30 } },
      { nodeId: "b", box: { x: 100, y: 100, width: 30, height: 30 } },
      { nodeId: "c", box: { x: 20, y: 20, width: 200, height: 200 } }
    ];
    const rect = { x: 10, y: 10, width: 40, height: 40 };
    expect(marqueeSelection(rect, boxes).sort()).toEqual(["a", "c"]);
  });
});
