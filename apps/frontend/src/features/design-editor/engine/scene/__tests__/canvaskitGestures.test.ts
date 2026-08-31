import { describe, expect, it } from "../../__tests__/vitest-shim";
import type { Scene } from "../contracts";
import { minimalScene } from "./__fixtures__/minimalScene";
import {
  descriptorToScene,
  dragActionToOperations,
  handleAtPoint,
  resizeActionToOperation,
  screenToDescriptor
} from "../canvaskitGestures";
import type { Box } from "../transformerMath";

const BOX: Box = { x: 0, y: 0, width: 100, height: 100 };

function cloneScene(): Scene {
  return JSON.parse(JSON.stringify(minimalScene)) as Scene;
}

describe("canvaskit gesture glue (Wave 3 host)", () => {
  it("maps screen → descriptor → scene space", () => {
    const d = screenToDescriptor({ x: 220, y: 150 }, { x: 100, y: 50 }, 2);
    expect(d).toEqual({ x: 60, y: 50 });
    expect(descriptorToScene({ x: 60, y: 50 }, 2)).toEqual({ x: 30, y: 25 });
  });

  it("detects a resize handle grab within tolerance", () => {
    // Bottom-right corner is at (100,100) in descriptor space.
    expect(handleAtPoint({ x: 100, y: 100 }, BOX, 0, 1)).toBe("bottom-right");
    expect(handleAtPoint({ x: 0, y: 0 }, BOX, 0, 1)).toBe("top-left");
    expect(handleAtPoint({ x: 50, y: 0 }, BOX, 0, 1)).toBe("top");
    // Center of the box is not a handle.
    expect(handleAtPoint({ x: 50, y: 50 }, BOX, 0, 1)).toBeNull();
  });

  it("detects the rotate handle above the box", () => {
    // Rotate handle sits 22 descriptor units above the top-center (50,0) → (50,-22).
    expect(handleAtPoint({ x: 50, y: -22 }, BOX, 0, 1)).toBe("rotate");
  });

  it("scales the handle tolerance by zoom", () => {
    // At zoom 2 the screen radius 7 maps to 3.5 descriptor units; a point 5
    // descriptor units from the corner should miss.
    expect(handleAtPoint({ x: 105, y: 100 }, BOX, 0, 2)).toBeNull();
    // …but within 3.5 it hits.
    expect(handleAtPoint({ x: 102, y: 100 }, BOX, 0, 2)).toBe("bottom-right");
  });

  it("converts drag and resize actions to canonical operations", () => {
    const scene = cloneScene();
    const node = scene.nodes.node_contact_name;
    const page = scene.pages.page_a4;
    const pageOrigin = { x: 0, y: 0 };

    const [drag] = dragActionToOperations({ x: 30, y: 30, width: 100, height: 28 }, scene, node, page, pageOrigin);
    expect(drag).toBeDefined();
    expect(drag.kind).toBe("update_node");

    const resize = resizeActionToOperation(
      { x: 0, y: 0, width: 200, height: 56 },
      0,
      scene,
      node,
      page,
      pageOrigin
    );
    expect(resize).not.toBeNull();
    expect(resize!.kind).toBe("update_node");
  });
});
