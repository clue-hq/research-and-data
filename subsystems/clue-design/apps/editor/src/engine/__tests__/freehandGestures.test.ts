/**
 * Phase 1d freehand gesture gate + commit semantics:
 * - the editability gate opens for pinned nodes and Free-container children
 * - a pinned drag commits to the page-space absolute_box with NO parent
 *   clamp (drags are honored past boundaries — the render clips, Moda-style)
 * - a container drag carries pinned descendants' boxes by the same delta
 * - a pinned resize rewrites the box and bakes the Fixed size in one patch
 */
import { describe, expect, it } from "vitest";
import type { Node, NodePatch, Operation, Scene } from "../contracts";
import { minimalScene } from "@/fixtures/minimalScene";
import { canvasDragOperations, canvasResizeOperation } from "../canvasOperations";
import {
  isNodeDirectGeometryEditable,
  isNodeFreehand,
  isNodePinned
} from "../sceneQueries";

function cloneScene(): Scene {
  return JSON.parse(JSON.stringify(minimalScene)) as Scene;
}

function baseNode(id: string): Node {
  return {
    id,
    name: id,
    kind: { kind: "rect" },
    transform: { x: 0, y: 0, rotation: 0, skew_x: 0, skew_y: 0, flip_x: false, flip_y: false },
    size: {
      width: { kind: "fixed", value: 40 },
      height: { kind: "fixed", value: 20 }
    },
    children: [],
    fills: [],
    strokes: [],
    corner: { top_left: 0, top_right: 0, bottom_right: 0, bottom_left: 0 },
    opacity: 1,
    clip: false,
    layout: null,
    computed: null,
    locked: false
  };
}

/** minimalScene + a clipping column stack holding a managed child and a
 * pinned child (pinned at page-space (150,150)). */
function freehandScene(): Scene {
  const scene = cloneScene();
  const pageId = Object.keys(scene.pages)[0];
  // Identity canvas↔scene conversion so box coordinates assert exactly.
  scene.pages[pageId].size = { ...scene.pages[pageId].size, unit: "px", width: 800, height: 600 };
  const stack = baseNode("stack");
  stack.kind = { kind: "auto_layout", direction: "column", wrap: false };
  stack.size = {
    width: { kind: "fixed", value: 100 },
    height: { kind: "fixed", value: 100 }
  };
  stack.transform.x = 20;
  stack.transform.y = 20;
  stack.clip = true;
  stack.layout = { gap: 10, padding: [0, 0, 0, 0], grow: 0 };
  stack.children = ["managed_child", "pinned_child"];
  stack.computed = {
    layout_bounds: { x: 20, y: 20, width: 100, height: 100 },
    render_bounds: { x: 20, y: 20, width: 100, height: 100 }
  };

  const managed = baseNode("managed_child");
  managed.computed = {
    layout_bounds: { x: 20, y: 20, width: 40, height: 20 },
    render_bounds: { x: 20, y: 20, width: 40, height: 20 }
  };

  const pinned = baseNode("pinned_child");
  pinned.position_mode = "absolute";
  pinned.absolute_box = { x: 150, y: 150, width: 40, height: 20 };
  pinned.computed = {
    layout_bounds: { x: 150, y: 150, width: 40, height: 20 },
    render_bounds: { x: 150, y: 150, width: 40, height: 20 }
  };

  scene.nodes.stack = stack;
  scene.nodes.managed_child = managed;
  scene.nodes.pinned_child = pinned;
  scene.pages[pageId].children.push("stack");
  return scene;
}

function pageOf(scene: Scene) {
  return scene.pages[Object.keys(scene.pages)[0]];
}

const ORIGIN = { x: 0, y: 0 };

function patchOf(operation: Operation): NodePatch {
  if (operation.kind !== "update_node") {
    throw new Error(`expected update_node, got ${operation.kind}`);
  }
  return operation.patch;
}

describe("freehand editability gate (Phase 1d)", () => {
  it("opens for pinned children of auto-layout containers", () => {
    const scene = freehandScene();
    expect(isNodePinned(scene, "pinned_child")).toBe(true);
    expect(isNodeFreehand(scene, "pinned_child")).toBe(true);
    expect(isNodeDirectGeometryEditable(scene, "pinned_child")).toBe(true);
    // Managed siblings stay solver-owned.
    expect(isNodeDirectGeometryEditable(scene, "managed_child")).toBe(false);
  });

  it("opens for children of a Free container", () => {
    const scene = freehandScene();
    scene.nodes.stack.layout = { ...scene.nodes.stack.layout!, layout_mode: "free" };
    expect(isNodeFreehand(scene, "managed_child")).toBe(true);
    expect(isNodeDirectGeometryEditable(scene, "managed_child")).toBe(true);
  });
});

describe("pinned drag commits (Phase 1d)", () => {
  it("rewrites the page-space absolute_box without any parent clamp", () => {
    const scene = freehandScene();
    const page = pageOf(scene);
    // Drag far outside the clipped stack AND the page — must be honored.
    const ops = canvasDragOperations({
      scene,
      node: scene.nodes.pinned_child,
      page,
      pageOrigin: ORIGIN,
      canvasX: 500,
      canvasY: 400
    });
    expect(ops).toHaveLength(1);
    const patch = patchOf(ops[0]);
    expect(patch.absolute_box).toEqual({
      kind: "set",
      value: { x: 500, y: 400, width: 40, height: 20 }
    });
    // A move is not a resize: the size spec stays untouched.
    expect(patch.size).toEqual({ kind: "unchanged" });
    // Stale geometry is invalidated in the same patch.
    expect(patch.computed).toEqual({ kind: "clear" });
    // The flow-input transform is NOT written for pinned nodes.
    expect(patch.transform).toEqual({ kind: "unchanged" });
  });

  it("resize rewrites the box and bakes the Fixed size in one patch", () => {
    const scene = freehandScene();
    const page = pageOf(scene);
    const op = canvasResizeOperation({
      scene,
      node: scene.nodes.pinned_child,
      page,
      pageOrigin: ORIGIN,
      transform: { canvasX: 160, canvasY: 160, rotation: 0, scaleX: 2, scaleY: 3 }
    });
    expect(op).not.toBeNull();
    const patch = patchOf(op!);
    expect(patch.absolute_box).toEqual({
      kind: "set",
      value: { x: 160, y: 160, width: 80, height: 60 }
    });
    expect(patch.size).toEqual({
      kind: "set",
      value: {
        width: { kind: "fixed", value: 80 },
        height: { kind: "fixed", value: 60 }
      }
    });
  });
});

describe("container drags carry pinned descendants (Phase 1d)", () => {
  it("emits one box translation per pinned descendant, same delta", () => {
    const scene = freehandScene();
    const page = pageOf(scene);
    // Drag the stack from (20,20) to (35,90) — clear of snap guides:
    // delta (+15,+70). The managed primary op keeps its snap/clamp path,
    // and the pin translation follows the committed (possibly snapped)
    // delta so the composition moves as one.
    const ops = canvasDragOperations({
      scene,
      node: scene.nodes.stack,
      page,
      pageOrigin: ORIGIN,
      canvasX: 35,
      canvasY: 90
    });
    expect(ops).toHaveLength(2);
    expect(ops[0].kind).toBe("update_node");
    const translation = patchOf(ops[1]);
    expect(ops[1].kind === "update_node" && ops[1].node_id).toBe("pinned_child");
    expect(translation.absolute_box).toEqual({
      kind: "set",
      value: { x: 165, y: 220, width: 40, height: 20 }
    });
  });

  it("emits no translations when the drag lands where it started", () => {
    const scene = freehandScene();
    const page = pageOf(scene);
    const ops = canvasDragOperations({
      scene,
      node: scene.nodes.stack,
      page,
      pageOrigin: ORIGIN,
      canvasX: 20,
      canvasY: 20
    });
    expect(ops).toHaveLength(1);
  });
});

describe("free-container child drags (Phase 1d)", () => {
  it("commits a parent-relative transform without clamping", () => {
    const scene = freehandScene();
    scene.nodes.stack.layout = { ...scene.nodes.stack.layout!, layout_mode: "free" };
    const page = pageOf(scene);
    // Page-space (150, 90) inside a parent at (20,20) → transform (130, 70);
    // width 40 from x=150 pokes past the parent's right edge (120) — honored.
    const ops = canvasDragOperations({
      scene,
      node: scene.nodes.managed_child,
      page,
      pageOrigin: ORIGIN,
      canvasX: 150,
      canvasY: 90
    });
    expect(ops).toHaveLength(1);
    const patch = patchOf(ops[0]);
    expect(patch.transform).toEqual({
      kind: "set",
      value: {
        x: 130,
        y: 70,
        rotation: 0,
        skew_x: 0,
        skew_y: 0,
        flip_x: false,
        flip_y: false
      }
    });
  });
});
