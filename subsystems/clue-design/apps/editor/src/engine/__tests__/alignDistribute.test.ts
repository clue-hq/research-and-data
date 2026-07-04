import { describe, expect, it } from "vitest";
import type { Node, Scene } from "../contracts";
import {
  alignDistributeCommitOperation,
  alignNodesOperations,
  computeAlignTargets,
  computeDistributeTargets,
  distributeNodesOperations,
  type AlignDistributeItem
} from "../alignDistribute";

describe("computeAlignTargets", () => {
  const items = (): AlignDistributeItem[] => [
    { id: "a", box: { x: 0, y: 0, width: 10, height: 10 } },
    { id: "b", box: { x: 50, y: 30, width: 20, height: 40 } },
    { id: "c", box: { x: 100, y: 60, width: 30, height: 10 } }
  ];

  it("requires 2+ items", () => {
    expect(computeAlignTargets([items()[0]], "left")).toEqual([]);
    expect(computeAlignTargets([], "left")).toEqual([]);
  });

  it("aligns left to the union min-x", () => {
    // union x spans [0, 130) since c ends at 100+30=130
    const targets = computeAlignTargets(items(), "left");
    expect(targets).toEqual([
      { id: "b", box: { x: 0, y: 30, width: 20, height: 40 } },
      { id: "c", box: { x: 0, y: 60, width: 30, height: 10 } }
    ]);
    // a is already at union min-x (0), so it's unchanged and omitted
  });

  it("aligns right to the union max-x (trailing edge)", () => {
    // union max-x = max(0+10, 50+20, 100+30) = 130
    const targets = computeAlignTargets(items(), "right");
    expect(targets).toEqual([
      { id: "a", box: { x: 120, y: 0, width: 10, height: 10 } },
      { id: "b", box: { x: 110, y: 30, width: 20, height: 40 } }
      // c already ends at 130, unchanged and omitted
    ]);
  });

  it("aligns center-h to the union horizontal midpoint", () => {
    // union: x=0, width=130 -> center = 65
    const targets = computeAlignTargets(items(), "center-h");
    expect(targets).toEqual([
      { id: "a", box: { x: 60, y: 0, width: 10, height: 10 } },
      { id: "b", box: { x: 55, y: 30, width: 20, height: 40 } },
      { id: "c", box: { x: 50, y: 60, width: 30, height: 10 } }
    ]);
  });

  it("aligns top to the union min-y", () => {
    const targets = computeAlignTargets(items(), "top");
    expect(targets).toEqual([
      { id: "b", box: { x: 50, y: 0, width: 20, height: 40 } },
      { id: "c", box: { x: 100, y: 0, width: 30, height: 10 } }
    ]);
  });

  it("aligns bottom to the union max-y (trailing edge)", () => {
    // union max-y = max(0+10, 30+40, 60+10) = 70
    const targets = computeAlignTargets(items(), "bottom");
    expect(targets).toEqual([
      { id: "a", box: { x: 0, y: 60, width: 10, height: 10 } }
      // b already ends at 70 (30+40) and c already ends at 70 (60+10) —
      // both unchanged and omitted
    ]);
  });

  it("aligns middle-v to the union vertical midpoint", () => {
    // union: y=0, height=70 -> center = 35
    const targets = computeAlignTargets(items(), "middle-v");
    expect(targets).toEqual([
      { id: "a", box: { x: 0, y: 30, width: 10, height: 10 } },
      { id: "b", box: { x: 50, y: 15, width: 20, height: 40 } },
      { id: "c", box: { x: 100, y: 30, width: 30, height: 10 } }
    ]);
  });

  it("only returns changed boxes — an already-aligned item is omitted", () => {
    const alreadyLeft: AlignDistributeItem[] = [
      { id: "a", box: { x: 0, y: 0, width: 10, height: 10 } },
      { id: "b", box: { x: 0, y: 20, width: 10, height: 10 } }
    ];
    expect(computeAlignTargets(alreadyLeft, "left")).toEqual([]);
  });

  it("never changes width/height", () => {
    for (const mode of ["left", "center-h", "right", "top", "middle-v", "bottom"] as const) {
      const targets = computeAlignTargets(items(), mode);
      for (const target of targets) {
        const original = items().find((item) => item.id === target.id)!;
        expect(target.box.width).toBe(original.box.width);
        expect(target.box.height).toBe(original.box.height);
      }
    }
  });
});

describe("computeDistributeTargets", () => {
  it("requires 3+ items", () => {
    const two: AlignDistributeItem[] = [
      { id: "a", box: { x: 0, y: 0, width: 10, height: 10 } },
      { id: "b", box: { x: 100, y: 0, width: 10, height: 10 } }
    ];
    expect(computeDistributeTargets(two, "horizontal")).toEqual([]);
  });

  it("distributes uneven sizes with exact equal gaps (horizontal)", () => {
    // a: [0,10) w=10  b: [40,70) w=30  c: [200,210) w=10
    // span = (200+10) - 0 = 210; totalSize = 10+30+10=50; gapCount=2
    // gap = (210-50)/2 = 80
    // first stays at x=0; b should land at 0+10+80=90; c stays at x=200
    const items: AlignDistributeItem[] = [
      { id: "a", box: { x: 0, y: 0, width: 10, height: 10 } },
      { id: "b", box: { x: 40, y: 0, width: 30, height: 10 } },
      { id: "c", box: { x: 200, y: 0, width: 10, height: 10 } }
    ];
    const targets = computeDistributeTargets(items, "horizontal");
    expect(targets).toEqual([{ id: "b", box: { x: 90, y: 0, width: 30, height: 10 } }]);

    // verify the gap invariant directly
    const bTarget = targets[0].box;
    const gapAB = bTarget.x - (items[0].box.x + items[0].box.width);
    const gapBC = items[2].box.x - (bTarget.x + bTarget.width);
    expect(gapAB).toBeCloseTo(80);
    expect(gapBC).toBeCloseTo(80);
  });

  it("distributes uneven sizes with exact equal gaps (vertical)", () => {
    const items: AlignDistributeItem[] = [
      { id: "a", box: { x: 0, y: 0, width: 10, height: 20 } },
      { id: "b", box: { x: 0, y: 60, width: 10, height: 10 } },
      { id: "c", box: { x: 0, y: 300, width: 10, height: 40 } }
    ];
    // span = (300+40) - 0 = 340; totalSize = 20+10+40=70; gapCount=2
    // gap = (340-70)/2 = 135
    // b should land at y = 0+20+135 = 155
    const targets = computeDistributeTargets(items, "vertical");
    expect(targets).toEqual([{ id: "b", box: { x: 0, y: 155, width: 10, height: 10 } }]);
  });

  it("sorts unsorted input by box center before distributing", () => {
    // Provide out of order: c (rightmost), a (leftmost), b (middle)
    const items: AlignDistributeItem[] = [
      { id: "c", box: { x: 200, y: 0, width: 10, height: 10 } },
      { id: "a", box: { x: 0, y: 0, width: 10, height: 10 } },
      { id: "b", box: { x: 40, y: 0, width: 30, height: 10 } }
    ];
    const targets = computeDistributeTargets(items, "horizontal");
    // same result as the sorted case: only "b" (the true middle) moves
    expect(targets).toEqual([{ id: "b", box: { x: 90, y: 0, width: 30, height: 10 } }]);
  });

  it("keeps first and last fixed even when they don't move", () => {
    const items: AlignDistributeItem[] = [
      { id: "a", box: { x: 0, y: 0, width: 10, height: 10 } },
      { id: "b", box: { x: 45, y: 0, width: 10, height: 10 } },
      { id: "c", box: { x: 90, y: 0, width: 10, height: 10 } }
    ];
    // already evenly spaced -> gap = (100-30)/2 = 35; b already at 0+10+35=45
    const targets = computeDistributeTargets(items, "horizontal");
    expect(targets).toEqual([]);
  });

  it("distributes 4 items with two moving middles", () => {
    const items: AlignDistributeItem[] = [
      { id: "a", box: { x: 0, y: 0, width: 10, height: 10 } },
      { id: "b", box: { x: 20, y: 0, width: 10, height: 10 } },
      { id: "c", box: { x: 200, y: 0, width: 10, height: 10 } },
      { id: "d", box: { x: 300, y: 0, width: 10, height: 10 } }
    ];
    // span = 310 - 0 = 310; totalSize = 40; gapCount = 3; gap = 90
    // b: 0+10+90=100; c: 100+10+90=200 (unchanged, omitted)
    const targets = computeDistributeTargets(items, "horizontal");
    expect(targets).toEqual([{ id: "b", box: { x: 100, y: 0, width: 10, height: 10 } }]);
  });
});

describe("alignDistributeCommitOperation", () => {
  function baseNode(overrides: Partial<Node> = {}): Node {
    return {
      id: "n",
      name: "Node",
      kind: { kind: "rect" },
      transform: { x: 5, y: 5, rotation: 0, skew_x: 0, skew_y: 0, flip_x: false, flip_y: false },
      size: { width: { kind: "fixed", value: 10 }, height: { kind: "fixed", value: 10 } },
      children: [],
      fills: [],
      strokes: [],
      corner: { top_left: 0, top_right: 0, bottom_right: 0, bottom_left: 0 },
      opacity: 1,
      clip: false,
      layout: null,
      computed: { layout_bounds: { x: 5, y: 5, width: 10, height: 10 }, render_bounds: { x: 5, y: 5, width: 10, height: 10 } },
      locked: false,
      ...overrides
    } as Node;
  }

  function sceneWith(node: Node, extraNodes: Record<string, Node> = {}): Scene {
    return {
      document: { id: "doc", title: "Doc", artifact_type: "linkedin_ad" },
      pages: {
        page_a4: { id: "page_a4", name: "A4", size: { width: 210, height: 297, unit: "mm" }, children: [node.id] }
      },
      nodes: { [node.id]: node, ...extraNodes },
      slots: {},
      assets: {}
    } as unknown as Scene;
  }

  it("commits a pinned node as an absolute_box update, preserving its size", () => {
    const node = baseNode({ position_mode: "absolute", absolute_box: { x: 5, y: 5, width: 40, height: 20 } });
    const scene = sceneWith(node);
    const operation = alignDistributeCommitOperation(scene, node, { x: 100, y: 60, width: 40, height: 20 });
    expect(operation).toEqual({
      kind: "update_node",
      node_id: "n",
      patch: expect.objectContaining({
        absolute_box: { kind: "set", value: { x: 100, y: 60, width: 40, height: 20 } }
      })
    });
  });

  it("commits a freehand child of a Free auto-layout container as a parent-rebased transform", () => {
    const parent = baseNode({
      id: "free-parent",
      kind: { kind: "auto_layout", direction: "column", wrap: false },
      layout: { gap: 0, grow: 0, padding: [0, 0, 0, 0], layout_mode: "free" },
      children: ["n"],
      computed: { layout_bounds: { x: 20, y: 20, width: 200, height: 200 }, render_bounds: { x: 20, y: 20, width: 200, height: 200 } }
    });
    const node = baseNode({ transform: { x: 3, y: 3, rotation: 0, skew_x: 0, skew_y: 0, flip_x: false, flip_y: false } });
    const scene = sceneWith(node, { "free-parent": parent });
    scene.pages.page_a4.children = ["free-parent"];

    // target box in page space: parent origin is (20,20)
    const operation = alignDistributeCommitOperation(scene, node, { x: 120, y: 90, width: 10, height: 10 });
    expect(operation).toEqual({
      kind: "update_node",
      node_id: "n",
      patch: expect.objectContaining({
        transform: { kind: "set", value: { ...node.transform, x: 100, y: 70 } }
      })
    });
  });

  it("returns null for a node that is neither pinned nor freehand", () => {
    const node = baseNode();
    const scene = sceneWith(node);
    expect(alignDistributeCommitOperation(scene, node, { x: 1, y: 1, width: 10, height: 10 })).toBeNull();
  });
});

describe("alignNodesOperations / distributeNodesOperations", () => {
  function pinnedNode(id: string, box: { x: number; y: number; width: number; height: number }): Node {
    return {
      id,
      name: id,
      kind: { kind: "rect" },
      transform: { x: box.x, y: box.y, rotation: 0, skew_x: 0, skew_y: 0, flip_x: false, flip_y: false },
      size: { width: { kind: "fixed", value: box.width }, height: { kind: "fixed", value: box.height } },
      children: [],
      fills: [],
      strokes: [],
      corner: { top_left: 0, top_right: 0, bottom_right: 0, bottom_left: 0 },
      opacity: 1,
      clip: false,
      layout: null,
      computed: { layout_bounds: box, render_bounds: box },
      locked: false,
      position_mode: "absolute",
      absolute_box: box
    } as Node;
  }

  function sceneOf(nodes: Node[]): Scene {
    return {
      document: { id: "doc", title: "Doc", artifact_type: "linkedin_ad" },
      pages: {
        page_a4: { id: "page_a4", name: "A4", size: { width: 210, height: 297, unit: "mm" }, children: nodes.map((n) => n.id) }
      },
      nodes: Object.fromEntries(nodes.map((n) => [n.id, n])),
      slots: {},
      assets: {}
    } as unknown as Scene;
  }

  it("builds one UpdateNode op per changed node for align, ready for one applyOperations batch", () => {
    const a = pinnedNode("a", { x: 0, y: 0, width: 10, height: 10 });
    const b = pinnedNode("b", { x: 50, y: 30, width: 20, height: 40 });
    const scene = sceneOf([a, b]);

    const ops = alignNodesOperations(scene, ["a", "b"], "left");
    expect(ops).toHaveLength(1);
    expect(ops[0]).toEqual({
      kind: "update_node",
      node_id: "b",
      patch: expect.objectContaining({
        absolute_box: { kind: "set", value: { x: 0, y: 30, width: 20, height: 40 } }
      })
    });
  });

  it("builds ops for distribute, skipping unchanged first/last", () => {
    const a = pinnedNode("a", { x: 0, y: 0, width: 10, height: 10 });
    const b = pinnedNode("b", { x: 40, y: 0, width: 30, height: 10 });
    const c = pinnedNode("c", { x: 200, y: 0, width: 10, height: 10 });
    const scene = sceneOf([a, b, c]);

    const ops = distributeNodesOperations(scene, ["a", "b", "c"], "horizontal");
    expect(ops).toHaveLength(1);
    expect(ops[0].kind).toBe("update_node");
    expect(ops[0]).toMatchObject({ node_id: "b" });
  });

  it("skips a node with no resolvable page-space box", () => {
    const a = pinnedNode("a", { x: 0, y: 0, width: 10, height: 10 });
    const unlaidOut = { ...pinnedNode("b", { x: 0, y: 0, width: 10, height: 10 }), computed: null, absolute_box: null };
    const scene = sceneOf([a, unlaidOut]);

    const ops = alignNodesOperations(scene, ["a", "b"], "left");
    expect(ops).toEqual([]);
  });
});
