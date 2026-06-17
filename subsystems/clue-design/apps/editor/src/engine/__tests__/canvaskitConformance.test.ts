import { describe, expect, it } from "vitest";
import type { Scene } from "../contracts";
import { minimalScene } from "@/fixtures/minimalScene";
import { canvasDragOperation, canvasResizeOperation } from "../canvasOperations";
import { dragActionToOperation, resizeActionToOperation } from "../canvaskitGestures";
import {
  gestureReducer,
  initialGestureState,
  type GestureEvent,
  type GestureState,
  type PressTarget
} from "../gestureMachine";
import { nodeDescriptor } from "../renderAdapter";
import type { Box } from "../transformerMath";

/**
 * Wave 3 C6 conformance: the CanvasKit interaction path must emit the SAME
 * canonical operations as the direct (Konva-equivalent) path — both reuse
 * canvasDragOperation / canvasResizeOperation, so the envelopes match by
 * construction. This pins it: a gesture simulated through the pure reducer +
 * action→operation conversion deep-equals the operation the direct builder
 * produces for the same final geometry.
 */

const PAGE_ORIGIN = { x: 0, y: 0 };

/** A px-unit page (unitScale 1) so descriptor space == scene space. */
function pxScene(): Scene {
  const scene = JSON.parse(JSON.stringify(minimalScene)) as Scene;
  scene.pages.page_a4 = {
    ...scene.pages.page_a4,
    size: { width: 400, height: 300, unit: "px", preset: "custom", orientation: "landscape" }
  };
  const node = scene.nodes.node_contact_name;
  node.transform = { ...node.transform, x: 40, y: 50 };
  node.size = { width: { kind: "fixed", value: 120 }, height: { kind: "fixed", value: 40 } };
  node.computed = {
    layout_bounds: { x: 40, y: 50, width: 120, height: 40 },
    render_bounds: { x: 40, y: 50, width: 120, height: 40 }
  };
  return scene;
}

function drive(events: GestureEvent[]) {
  let state: GestureState = initialGestureState;
  let last = null as ReturnType<typeof gestureReducer>["action"] | null;
  for (const event of events) {
    const r = gestureReducer(state, event);
    state = r.state;
    last = r.action;
  }
  return last;
}

describe("CanvasKit interaction conformance (Wave 3 C6)", () => {
  it("a simulated drag emits the same operation as the direct builder", () => {
    const scene = pxScene();
    const node = scene.nodes.node_contact_name;
    const page = scene.pages.page_a4;
    const box: Box = { x: 40, y: 50, width: 120, height: 40 };
    const target: PressTarget = { kind: "node", nodeId: node.id, box, rotation: 0 };

    // Grab at (60,60) and drag by (+30,+20) → final top-left (70,70).
    const action = drive([
      { kind: "down", point: { x: 60, y: 60 }, target, modifiers: {} },
      { kind: "move", point: { x: 90, y: 80 }, modifiers: {} },
      { kind: "up", point: { x: 90, y: 80 }, modifiers: {} }
    ]);
    expect(action?.kind).toBe("drag");
    const gestureOp = dragActionToOperation((action as { box: Box }).box, scene, node, page, PAGE_ORIGIN);

    const directOp = canvasDragOperation({
      scene,
      node,
      page,
      pageOrigin: PAGE_ORIGIN,
      canvasX: 70,
      canvasY: 70
    });

    expect(gestureOp).toEqual(directOp);
  });

  it("a simulated resize emits the same operation as the direct builder", () => {
    const scene = pxScene();
    const node = scene.nodes.node_contact_name;
    const page = scene.pages.page_a4;
    const box: Box = { x: 40, y: 50, width: 120, height: 40 };
    const target: PressTarget = {
      kind: "handle",
      nodeId: node.id,
      handle: "bottom-right",
      box,
      rotation: 0
    };

    // Drag the bottom-right handle to (200,140) → new size 160×90 anchored at (40,50).
    const action = drive([
      { kind: "down", point: { x: 160, y: 90 }, target, modifiers: {} },
      { kind: "move", point: { x: 200, y: 140 }, modifiers: {} },
      { kind: "up", point: { x: 200, y: 140 }, modifiers: {} }
    ]);
    expect(action?.kind).toBe("resize");
    const resizedBox = (action as { box: Box }).box;
    const gestureOp = resizeActionToOperation(resizedBox, 0, scene, node, page, PAGE_ORIGIN);

    // The direct path expresses the same final box as scale factors over the
    // base render size (120×40): scaleX = 160/120, scaleY = 90/40.
    const directOp = canvasResizeOperation({
      scene,
      node,
      page,
      pageOrigin: PAGE_ORIGIN,
      transform: {
        canvasX: resizedBox.x,
        canvasY: resizedBox.y,
        rotation: 0,
        scaleX: resizedBox.width / 120,
        scaleY: resizedBox.height / 40
      }
    });

    expect(gestureOp).toEqual(directOp);
  });
});
