import { describe, expect, it } from "vitest";
import { minimalScene } from "@/fixtures/minimalScene";
import type { Operation, Scene } from "../contracts";
import { canvasDragOperation, canvasResizeOperation, dragSnapGuides, resizeSnapGuides } from "../canvasOperations";

describe("canvas operations", () => {
  it("emits canonical transform operations for dragging on a custom page", () => {
    const scene = customPixelScene();
    const node = scene.nodes.node_contact_name;
    const page = scene.pages.page_a4;

    const operation = canvasDragOperation({
      scene,
      node,
      page,
      pageOrigin: {
        x: 12,
        y: 20
      },
      canvasX: 240,
      canvasY: 180
    });

    const transform = expectUpdateNode(operation).patch.transform;
    expect(transform).toEqual({
      kind: "set",
      value: {
        ...node.transform,
        x: 228,
        y: 160
      }
    });
  });

  it("clamps drag operations to the parent page bounds", () => {
    const scene = customPixelScene();
    scene.pages.page_a4.size = {
      width: 300,
      height: 100,
      unit: "px",
      preset: "custom",
      orientation: "landscape"
    };
    const node = scene.nodes.node_contact_name;

    const operation = canvasDragOperation({
      scene,
      node,
      page: scene.pages.page_a4,
      pageOrigin: {
        x: 0,
        y: 0
      },
      canvasX: 1000,
      canvasY: 1000
    });

    const transform = expectUpdateNode(operation).patch.transform;
    expect(transform).toEqual({
      kind: "set",
      value: {
        ...node.transform,
        x: 140,
        y: 72
      }
    });
  });

  it("snaps drag operations to safe-area guides", () => {
    const scene = customPixelScene();
    scene.pages.page_a4.safe_area = {
      x: 72,
      y: 72,
      width: 936,
      height: 936
    };
    const node = scene.nodes.node_contact_name;

    const operation = canvasDragOperation({
      scene,
      node,
      page: scene.pages.page_a4,
      pageOrigin: {
        x: 0,
        y: 0
      },
      canvasX: 69,
      canvasY: 74
    });

    const transform = expectUpdateNode(operation).patch.transform;
    expect(transform).toEqual({
      kind: "set",
      value: {
        ...node.transform,
        x: 72,
        y: 72
      }
    });
  });

  it("snaps drag operations to the page center", () => {
    const scene = customPixelScene();
    const node = scene.nodes.node_contact_name;

    const operation = canvasDragOperation({
      scene,
      node,
      page: scene.pages.page_a4,
      pageOrigin: {
        x: 0,
        y: 0
      },
      canvasX: 464,
      canvasY: 530
    });

    const transform = expectUpdateNode(operation).patch.transform;
    expect(transform).toEqual({
      kind: "set",
      value: {
        ...node.transform,
        x: 460,
        y: 526
      }
    });
  });

  it("emits combined transform and size operations for resize gestures", () => {
    const scene = customPixelScene();
    const node = scene.nodes.node_contact_name;

    const operation = canvasResizeOperation({
      scene,
      node,
      page: scene.pages.page_a4,
      pageOrigin: {
        x: 10,
        y: 20
      },
      transform: {
        canvasX: 54,
        canvasY: 82,
        rotation: 8,
        scaleX: 1.5,
        scaleY: 2
      }
    });

    const update = expectUpdateNode(operation);
    expect(update.patch.transform).toEqual({
      kind: "set",
      value: {
        ...node.transform,
        x: 44,
        y: 62,
        rotation: 8
      }
    });
    expect(update.patch.size).toEqual({
      kind: "set",
      value: {
        width: {
          kind: "fixed",
          value: 240
        },
        height: {
          kind: "fixed",
          value: 56
        }
      }
    });
  });

  it("clamps resize gestures to the parent page bounds", () => {
    const scene = customPixelScene();
    scene.pages.page_a4.size = {
      width: 300,
      height: 100,
      unit: "px",
      preset: "custom",
      orientation: "landscape"
    };
    const node = scene.nodes.node_contact_name;

    const operation = canvasResizeOperation({
      scene,
      node,
      page: scene.pages.page_a4,
      pageOrigin: {
        x: 0,
        y: 0
      },
      transform: {
        canvasX: 20,
        canvasY: 20,
        rotation: 0,
        scaleX: 4,
        scaleY: 5
      }
    });

    const update = expectUpdateNode(operation);
    expect(update.patch.transform).toEqual({
      kind: "set",
      value: {
        ...node.transform,
        x: 0,
        y: 0
      }
    });
    expect(update.patch.size).toEqual({
      kind: "set",
      value: {
        width: {
          kind: "fixed",
          value: 300
        },
        height: {
          kind: "fixed",
          value: 100
        }
      }
    });
  });

  it("snaps resize gestures to page bounds", () => {
    const scene = customPixelScene();
    const node = scene.nodes.node_contact_name;

    const operation = canvasResizeOperation({
      scene,
      node,
      page: scene.pages.page_a4,
      pageOrigin: {
        x: 0,
        y: 0
      },
      transform: {
        canvasX: 72,
        canvasY: 72,
        rotation: 0,
        scaleX: 1004 / 160,
        scaleY: 1
      }
    });

    const update = expectUpdateNode(operation);
    expect(update.patch.transform).toEqual({
      kind: "set",
      value: {
        ...node.transform,
        x: 72,
        y: 72,
        rotation: 0
      }
    });
    expect(update.patch.size).toEqual({
      kind: "set",
      value: {
        width: {
          kind: "fixed",
          value: 1008
        },
        height: {
          kind: "fixed",
          value: 28
        }
      }
    });
  });

  it("does not emit operations for locked or layout-managed nodes", () => {
    const scene = customPixelScene();
    scene.nodes.node_contact_name.locked = true;

    expect(
      canvasDragOperation({
        scene,
        node: scene.nodes.node_contact_name,
        page: scene.pages.page_a4,
        pageOrigin: {
          x: 0,
          y: 0
        },
        canvasX: 20,
        canvasY: 20
      })
    ).toBeNull();

    scene.nodes.node_contact_name.locked = false;
    scene.nodes.node_stack = {
      ...scene.nodes.node_contact_name,
      id: "node_stack",
      name: "Stack",
      kind: {
        kind: "auto_layout",
        direction: "column",
        wrap: false
      },
      children: ["node_contact_name"]
    };
    scene.pages.page_a4.children = ["node_stack"];

    expect(
      canvasResizeOperation({
        scene,
        node: scene.nodes.node_contact_name,
        page: scene.pages.page_a4,
        pageOrigin: {
          x: 0,
          y: 0
        },
        transform: {
          canvasX: 20,
          canvasY: 20,
          rotation: 0,
          scaleX: 2,
          scaleY: 2
        }
      })
    ).toBeNull();
  });

  it("snaps a pinned (Absolute) node's drag into its committed absolute_box (deliberate behavior change)", () => {
    // The bug this fixes: dragging an Absolute-mode node near a page edge
    // used to commit the raw, unsnapped position — no guide engaged, no
    // snap applied, even within the 8px threshold. Post-Phase-1, Absolute
    // nodes are exactly what humans drag by hand, and Moda snaps everything.
    const scene = customPixelScene();
    const node = {
      ...scene.nodes.node_contact_name,
      position_mode: "absolute" as const,
      absolute_box: { x: 24, y: 40, width: 160, height: 28 }
    };
    scene.nodes.node_contact_name = node;

    const operation = canvasDragOperation({
      scene,
      node,
      page: scene.pages.page_a4,
      pageOrigin: { x: 0, y: 0 },
      canvasX: 2, // within 6px threshold of the page's left edge (x=0)
      canvasY: 40
    });

    expect(operation).toMatchObject({
      kind: "update_node",
      node_id: "node_contact_name",
      patch: {
        absolute_box: {
          kind: "set",
          value: { x: 0, y: 40, width: 160, height: 28 }
        }
      }
    });
  });

  it("snaps a pinned (Absolute) node's resize into its committed absolute_box", () => {
    const scene = customPixelScene();
    const node = {
      ...scene.nodes.node_contact_name,
      position_mode: "absolute" as const,
      absolute_box: { x: 72, y: 72, width: 160, height: 28 }
    };
    scene.nodes.node_contact_name = node;

    // Byte-identical scaleX to "snaps resize gestures to page bounds":
    // stretches the trailing edge to the page's right bound (x=1080).
    const operation = canvasResizeOperation({
      scene,
      node,
      page: scene.pages.page_a4,
      pageOrigin: { x: 0, y: 0 },
      transform: {
        canvasX: 72,
        canvasY: 72,
        rotation: 0,
        scaleX: 1004 / 160,
        scaleY: 1
      }
    });

    expect(operation).toMatchObject({
      kind: "update_node",
      node_id: "node_contact_name",
      patch: {
        absolute_box: {
          kind: "set",
          value: { x: 72, y: 72, width: 1008, height: 28 }
        }
      }
    });
  });

  it("rejects non-finite or zero-scale resize gestures", () => {
    const scene = customPixelScene();
    const node = scene.nodes.node_contact_name;

    expect(
      canvasResizeOperation({
        scene,
        node,
        page: scene.pages.page_a4,
        pageOrigin: {
          x: 0,
          y: 0
        },
        transform: {
          canvasX: 20,
          canvasY: 20,
          rotation: 0,
          scaleX: 0,
          scaleY: 2
        }
      })
    ).toBeNull();
  });
});

describe("snap guides (visualization)", () => {
  it("reports an edge-to-edge guide when a drag snaps to the page's left edge", () => {
    const scene = customPixelScene();
    const node = scene.nodes.node_contact_name; // 160x28 at (24, 40)

    // canvasX=2 is within the 6px threshold of x=0 (matches the byte-identical
    // "snaps drag operations to safe-area guides"-style scenario, minus the
    // safe area — plain page-bounds snap).
    const guides = dragSnapGuides({
      scene,
      node,
      page: scene.pages.page_a4,
      pageOrigin: { x: 0, y: 0 },
      canvasX: 2,
      canvasY: 40
    });

    // "from"/"to" span the FULL page height (1080), not the dragged box's
    // own extent — a Moda-style full-bleed guide line.
    expect(guides).toEqual([{ axis: "x", position: 0, from: 0, to: 1080 }]);
  });

  it("reports a center-alignment guide when a drag snaps to the page midline", () => {
    const scene = customPixelScene();
    const node = scene.nodes.node_contact_name; // width 160

    // Page is 1080 wide; midline is x=540. Node center lands within threshold
    // when canvasX = 540 - width/2 + 2 = 462.
    const guides = dragSnapGuides({
      scene,
      node,
      page: scene.pages.page_a4,
      pageOrigin: { x: 0, y: 0 },
      canvasX: 462,
      canvasY: 40
    });

    expect(guides).toEqual([{ axis: "x", position: 540, from: 0, to: 1080 }]);
  });

  it("reports both axes when a drag snaps into a safe-area corner", () => {
    const scene = customPixelScene();
    scene.pages.page_a4.safe_area = { x: 72, y: 72, width: 936, height: 936 };
    const node = scene.nodes.node_contact_name;

    // Byte-identical target to the "snaps drag operations to safe-area
    // guides" operation test — both x and y engage at once.
    const guides = dragSnapGuides({
      scene,
      node,
      page: scene.pages.page_a4,
      pageOrigin: { x: 0, y: 0 },
      canvasX: 69,
      canvasY: 74
    });

    // Both guides span the full page extent on their cross axis (1080x1080).
    expect(guides).toEqual([
      { axis: "x", position: 72, from: 0, to: 1080 },
      { axis: "y", position: 72, from: 0, to: 1080 }
    ]);
  });

  it("reports no guides when nothing is within the snap threshold", () => {
    const scene = customPixelScene();
    const node = scene.nodes.node_contact_name;

    const guides = dragSnapGuides({
      scene,
      node,
      page: scene.pages.page_a4,
      pageOrigin: { x: 0, y: 0 },
      canvasX: 300,
      canvasY: 300
    });

    expect(guides).toEqual([]);
  });

  it("snaps a pinned (Absolute) node to page guides, same as a managed node (deliberate behavior change)", () => {
    // Post-Phase-1, Absolute nodes are exactly what humans drag by hand, and
    // Moda snaps everything — pinned/freehand exclusion from guide-snapping
    // was 4b-4 visualization-only scope, not a permanent policy.
    const scene = customPixelScene();
    const node = {
      ...scene.nodes.node_contact_name,
      position_mode: "absolute" as const,
      absolute_box: { x: 24, y: 40, width: 160, height: 28 }
    };
    scene.nodes.node_contact_name = node;

    // canvasX=2 is within the 6px threshold of the page's left edge (x=0).
    const guides = dragSnapGuides({
      scene,
      node,
      page: scene.pages.page_a4,
      pageOrigin: { x: 0, y: 0 },
      canvasX: 2,
      canvasY: 40
    });

    expect(guides).toEqual([{ axis: "x", position: 0, from: 0, to: 1080 }]);
  });

  it("reports a guide for a freehand child of a Free container (4c: snaps like a pinned node)", () => {
    // Deliberate behavior change (4c, mirrors the earlier pinned-node
    // change): a Free-container child's drag builds a page-space candidate
    // box from the parent's solved origin + the live offset and snaps it
    // against the same page guides — almost everything a human drags is
    // this class post-freeze_layout (every Stack container bakes to Free at
    // agent handoff).
    const scene = customPixelScene();
    scene.nodes.node_free_container = {
      ...scene.nodes.node_contact_name,
      id: "node_free_container",
      name: "Free container",
      kind: { kind: "auto_layout", direction: "column", wrap: false },
      layout: { gap: 0, grow: 0, padding: [0, 0, 0, 0], layout_mode: "free" },
      children: ["node_contact_name"]
    };
    scene.pages.page_a4.children = ["node_free_container"];

    // The free container has no `computed` bounds here, so its page-space
    // origin is (0,0) — the child's page-space candidate box is the raw
    // cursor position, same as the page-level fixture used elsewhere.
    const guides = dragSnapGuides({
      scene,
      node: scene.nodes.node_contact_name,
      page: scene.pages.page_a4,
      pageOrigin: { x: 0, y: 0 },
      canvasX: 2,
      canvasY: 40
    });

    expect(guides).toEqual([{ axis: "x", position: 0, from: 0, to: 1080 }]);
  });

  it("reports a guide for a resize that snaps its trailing edge to the page bound", () => {
    const scene = customPixelScene();
    const node = scene.nodes.node_contact_name;

    // Byte-identical target to "snaps resize gestures to page bounds".
    const guides = resizeSnapGuides({
      scene,
      node,
      page: scene.pages.page_a4,
      pageOrigin: { x: 0, y: 0 },
      transform: {
        canvasX: 72,
        canvasY: 72,
        rotation: 0,
        scaleX: 1004 / 160,
        scaleY: 1
      }
    });

    // Spans the full page height (1080), not the resized box's own extent.
    expect(guides).toEqual([{ axis: "x", position: 1080, from: 0, to: 1080 }]);
  });

  it("does not compute guides for locked or layout-managed nodes", () => {
    const scene = customPixelScene();
    scene.nodes.node_contact_name.locked = true;

    expect(
      dragSnapGuides({
        scene,
        node: scene.nodes.node_contact_name,
        page: scene.pages.page_a4,
        pageOrigin: { x: 0, y: 0 },
        canvasX: 2,
        canvasY: 2
      })
    ).toEqual([]);
  });
});

function customPixelScene(): Scene {
  const scene = JSON.parse(JSON.stringify(minimalScene)) as Scene;
  scene.pages.page_a4.size = {
    width: 1080,
    height: 1080,
    unit: "px",
    preset: "custom",
    orientation: "landscape"
  };
  return scene;
}

function expectUpdateNode(operation: Operation | null): Extract<Operation, { kind: "update_node" }> {
  expect(operation).toMatchObject({
    kind: "update_node",
    node_id: "node_contact_name"
  });
  return operation as Extract<Operation, { kind: "update_node" }>;
}
