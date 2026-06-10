import { describe, expect, it } from "vitest";
import type { Color, Node, Scene } from "../contracts";
import { minimalScene } from "@/fixtures/minimalScene";
import { colorToCss, nodeDescriptor, pageDescriptor, sceneUnitFromCanvas, sizeFromCanvas } from "../renderAdapter";

describe("render adapter", () => {
  it("projects page dimensions into canvas units", () => {
    const page = minimalScene.pages.page_a4;
    const descriptor = pageDescriptor(page);

    expect(descriptor.width).toBeCloseTo(793.7, 1);
    expect(descriptor.height).toBeCloseTo(1122.5, 1);
  });

  it("projects custom px page dimensions without preset coercion", () => {
    const page = {
      ...minimalScene.pages.page_a4,
      size: {
        width: 1080,
        height: 1080,
        unit: "px" as const,
        preset: "custom" as const,
        orientation: "landscape" as const
      }
    };
    const descriptor = pageDescriptor(page);

    expect(descriptor.width).toBe(1080);
    expect(descriptor.height).toBe(1080);
  });

  it("maps a text node to an editor render descriptor", () => {
    const page = minimalScene.pages.page_a4;
    const node = minimalScene.nodes.node_contact_name;
    const descriptor = nodeDescriptor(minimalScene, node, page);

    expect(descriptor.id).toBe("node_contact_name");
    expect(descriptor.kind).toBe("text");
    expect(descriptor.text?.content).toBe("Dr. Priya Sharma");
    expect(descriptor.x).toBeCloseTo(90.7, 1);
  });

  it("uses computed layout bounds for hug/fill-sized nodes", () => {
    const scene = cloneScene();
    const page = scene.pages.page_a4;
    const node: Node = {
      ...scene.nodes.node_contact_name,
      kind: {
        kind: "auto_layout",
        direction: "row",
        wrap: false
      },
      size: {
        width: {
          kind: "hug"
        },
        height: {
          kind: "fill",
          value: {
            weight: 1
          }
        }
      },
      computed: {
        layout_bounds: {
          x: 24,
          y: 40,
          width: 120,
          height: 32
        },
        render_bounds: {
          x: 24,
          y: 40,
          width: 124,
          height: 36
        }
      }
    };
    scene.nodes[node.id] = node;

    const descriptor = nodeDescriptor(scene, node, page);

    expect(descriptor.width).toBeCloseTo(453.5, 1);
    expect(descriptor.height).toBeCloseTo(120.9, 1);
    expect(descriptor.x).toBeCloseTo(90.7, 1);
    expect(descriptor.y).toBeCloseTo(151.2, 1);
  });

  it("accepts Rust-serialized token dimensions as unresolved editor sizes", () => {
    const scene = cloneScene();
    const page = scene.pages.page_a4;
    const node: Node = {
      ...scene.nodes.node_contact_name,
      size: {
        width: {
          kind: "token",
          value: {
            token: "space.xl"
          }
        },
        height: {
          kind: "token",
          value: {
            token: "space.md"
          }
        }
      },
      computed: null
    };
    scene.nodes[node.id] = node;

    const descriptor = nodeDescriptor(scene, node, page);

    expect(descriptor.width).toBe(0);
    expect(descriptor.height).toBe(0);
  });

  it("keeps logical groups non-visual when they have no fills", () => {
    const scene = cloneScene();
    const page = scene.pages.page_a4;
    const node: Node = {
      ...scene.nodes.node_contact_name,
      kind: {
        kind: "group"
      },
      fills: [],
      strokes: []
    };
    scene.nodes[node.id] = node;

    const descriptor = nodeDescriptor(scene, node, page);

    expect(descriptor.fill).toBe("transparent");
    expect(descriptor.stroke).toBeNull();
  });

  it("converts CSS alpha-last hex to CSS rgba", () => {
    const color: Color = {
      kind: "hex",
      value: "#ff000080"
    };

    expect(colorToCss(color)).toBe("rgba(255, 0, 0, 0.502)");
  });

  it("round trips canvas measurements back to scene units", () => {
    const page = minimalScene.pages.page_a4;

    expect(sceneUnitFromCanvas(96, page)).toBeCloseTo(25.4, 2);
    expect(sizeFromCanvas(96, 192, page)).toEqual({
      width: {
        kind: "fixed",
        value: 25.4
      },
      height: {
        kind: "fixed",
        value: 50.8
      }
    });
  });
});

function cloneScene(): Scene {
  return JSON.parse(JSON.stringify(minimalScene)) as Scene;
}
