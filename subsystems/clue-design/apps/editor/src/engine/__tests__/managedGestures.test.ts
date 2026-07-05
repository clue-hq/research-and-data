import { describe, expect, it } from "vitest";
import { minimalScene } from "@/fixtures/minimalScene";
import type { Node, Rect, Scene } from "../contracts";
import { reorderDropTarget } from "../managedGestures";

describe("reorderDropTarget (4c-C managed drag-to-reorder)", () => {
  it("resolves the middle gap in a vertical (column) stack", () => {
    const scene = columnStack();
    // Container spans y in [0, 300]; a/b/c each 100 tall, dragging "b" out
    // leaves a=[0,100] and c=[200,300] as the remaining siblings — the
    // pointer at y=150 (b's old midpoint) is still < c's midpoint (250), so
    // it resolves "before c", with the indicator at the a/c gap midpoint.
    const drop = reorderDropTarget(scene, "stack", "b", { x: 50, y: 150 });
    expect(drop).toEqual({
      index: 1,
      anchorId: "c",
      placement: "before",
      indicator: { axis: "y", position: 150, from: 0, to: 100 }
    });
  });

  it("resolves the first gap (before the first sibling) in a vertical stack", () => {
    const scene = columnStack();
    const drop = reorderDropTarget(scene, "stack", "c", { x: 50, y: 10 });
    expect(drop).toEqual({
      index: 0,
      anchorId: "a",
      placement: "before",
      indicator: { axis: "y", position: 0, from: 0, to: 100 }
    });
  });

  it("resolves the last gap (after the last sibling) in a vertical stack", () => {
    const scene = columnStack();
    const drop = reorderDropTarget(scene, "stack", "a", { x: 50, y: 290 });
    expect(drop).toEqual({
      index: 2,
      anchorId: "c",
      placement: "after",
      indicator: { axis: "y", position: 300, from: 0, to: 100 }
    });
  });

  it("resolves gaps in a horizontal (row) stack", () => {
    const scene = rowStack();
    const drop = reorderDropTarget(scene, "stack", "b", { x: 150, y: 50 });
    expect(drop).toEqual({
      index: 1,
      anchorId: "c",
      placement: "before",
      indicator: { axis: "x", position: 150, from: 0, to: 100 }
    });
  });

  it("skips the dragged node itself when computing gaps", () => {
    // Dragging "a" over its own old slot must not resolve against "a" — only
    // the remaining siblings (b, c) participate.
    const scene = columnStack();
    const drop = reorderDropTarget(scene, "stack", "a", { x: 50, y: 10 });
    expect(drop?.anchorId).toBe("b");
    expect(drop?.placement).toBe("before");
    expect(drop?.index).toBe(0);
  });

  it("is a no-op position when the pointer stays over the dragged node's own gap", () => {
    // Dragging "b" (originally index 1) and hovering back over its own slot
    // resolves to the same index it started at — callers treat index ===
    // current position as a no-op commit, but the function itself still
    // returns a valid (non-null) target; it doesn't special-case identity.
    const scene = columnStack();
    const drop = reorderDropTarget(scene, "stack", "b", { x: 50, y: 150 });
    expect(drop?.index).toBe(1);
  });

  it("returns null when the pointer is far outside the container bounds", () => {
    const scene = columnStack();
    const drop = reorderDropTarget(scene, "stack", "b", { x: 50, y: 1000 });
    expect(drop).toBeNull();
  });

  it("still resolves within the 40pt outside-cancel margin", () => {
    const scene = columnStack();
    // Container bottom edge is y=300; 30pt past it is within the 40pt margin.
    const drop = reorderDropTarget(scene, "stack", "b", { x: 50, y: 330 });
    expect(drop).not.toBeNull();
    expect(drop?.placement).toBe("after");
  });

  it("cancels just past the 40pt margin", () => {
    const scene = columnStack();
    const drop = reorderDropTarget(scene, "stack", "b", { x: 50, y: 341 });
    expect(drop).toBeNull();
  });

  it("returns null for a non-auto-layout / missing container", () => {
    const scene = columnStack();
    expect(reorderDropTarget(scene, "missing", "b", { x: 50, y: 150 })).toBeNull();
    scene.nodes.stack.computed = null;
    expect(reorderDropTarget(scene, "stack", "b", { x: 50, y: 150 })).toBeNull();
  });

  it("returns null when the container has no other children to anchor against", () => {
    const scene = columnStack();
    scene.nodes.stack.children = ["b"];
    const drop = reorderDropTarget(scene, "stack", "b", { x: 50, y: 150 });
    expect(drop).toBeNull();
  });

  it("insets the indicator span by the container's cross-axis padding", () => {
    const scene = columnStack();
    scene.nodes.stack.layout = { gap: 0, grow: 0, padding: [0, 10, 0, 20], layout_mode: "stack" };
    const drop = reorderDropTarget(scene, "stack", "b", { x: 50, y: 150 });
    // Column stack: cross axis is x. Container x in [0, 100] → inset by
    // padLeft=20 / padRight=10 => [20, 90]. Main-axis position (y) is the
    // a/c gap midpoint, unaffected by cross-axis padding.
    expect(drop?.indicator).toEqual({ axis: "y", position: 150, from: 20, to: 90 });
  });
});

/** Vertical (column) stack "stack" at page-space [0,0]-[100,300], containing
 * three 100pt-tall children a/b/c stacked top to bottom with no gap. */
function columnStack(): Scene {
  const scene = cloneScene();
  const template = scene.nodes.node_contact_name;
  const box = (rect: Rect): Node["computed"] => ({ layout_bounds: rect, render_bounds: rect });
  const a: Node = { ...template, id: "a", name: "A", kind: { kind: "rect" }, children: [], computed: box({ x: 0, y: 0, width: 100, height: 100 }) };
  const b: Node = { ...template, id: "b", name: "B", kind: { kind: "rect" }, children: [], computed: box({ x: 0, y: 100, width: 100, height: 100 }) };
  const c: Node = { ...template, id: "c", name: "C", kind: { kind: "rect" }, children: [], computed: box({ x: 0, y: 200, width: 100, height: 100 }) };
  const stack: Node = {
    ...template,
    id: "stack",
    name: "Stack",
    kind: { kind: "auto_layout", direction: "column", wrap: false },
    layout: { gap: 0, grow: 0, padding: [0, 0, 0, 0], layout_mode: "stack" },
    children: ["a", "b", "c"],
    computed: box({ x: 0, y: 0, width: 100, height: 300 })
  };
  scene.nodes = { a, b, c, stack };
  scene.pages.page_a4.children = ["stack"];
  return scene;
}

/** Horizontal (row) stack "stack" at page-space [0,0]-[300,100], containing
 * three 100pt-wide children a/b/c left to right with no gap. */
function rowStack(): Scene {
  const scene = cloneScene();
  const template = scene.nodes.node_contact_name;
  const box = (rect: Rect): Node["computed"] => ({ layout_bounds: rect, render_bounds: rect });
  const a: Node = { ...template, id: "a", name: "A", kind: { kind: "rect" }, children: [], computed: box({ x: 0, y: 0, width: 100, height: 100 }) };
  const b: Node = { ...template, id: "b", name: "B", kind: { kind: "rect" }, children: [], computed: box({ x: 100, y: 0, width: 100, height: 100 }) };
  const c: Node = { ...template, id: "c", name: "C", kind: { kind: "rect" }, children: [], computed: box({ x: 200, y: 0, width: 100, height: 100 }) };
  const stack: Node = {
    ...template,
    id: "stack",
    name: "Stack",
    kind: { kind: "auto_layout", direction: "row", wrap: false },
    layout: { gap: 0, grow: 0, padding: [0, 0, 0, 0], layout_mode: "stack" },
    children: ["a", "b", "c"],
    computed: box({ x: 0, y: 0, width: 300, height: 100 })
  };
  scene.nodes = { a, b, c, stack };
  scene.pages.page_a4.children = ["stack"];
  return scene;
}

function cloneScene(): Scene {
  return JSON.parse(JSON.stringify(minimalScene)) as Scene;
}
