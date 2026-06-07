import { describe, expect, it } from "vitest";
import type { Color } from "../contracts";
import { minimalScene } from "@/fixtures/minimalScene";
import { colorToCss, nodeDescriptor, pageDescriptor, sceneUnitFromCanvas, sizeFromCanvas } from "../renderAdapter";

describe("render adapter", () => {
  it("projects page dimensions into canvas units", () => {
    const page = minimalScene.pages.page_a4;
    const descriptor = pageDescriptor(page);

    expect(descriptor.width).toBeCloseTo(793.7, 1);
    expect(descriptor.height).toBeCloseTo(1122.5, 1);
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

  it("converts Flutter-style alpha-first hex to CSS rgba", () => {
    const color: Color = {
      kind: "hex",
      value: "#80ff0000"
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
