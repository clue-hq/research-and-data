import { describe, expect, it } from "vitest";
import { minimalScene } from "@/fixtures/minimalScene";
import type { Operation, Scene } from "../contracts";
import { canvasDragOperation, canvasResizeOperation } from "../canvasOperations";

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
