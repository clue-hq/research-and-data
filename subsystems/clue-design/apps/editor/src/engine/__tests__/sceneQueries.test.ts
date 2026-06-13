import { describe, expect, it } from "vitest";
import { minimalScene } from "@/fixtures/minimalScene";
import type { Scene } from "../contracts";
import type { Node } from "../contracts";
import {
  clampNodeTransformToParentBounds,
  firstPageId,
  flattenPageNodeIds,
  isContainerNode,
  isNodeDirectGeometryEditable,
  nodeIdForAsset,
  pageIdForNode,
  slotBoundNodeSummaries,
  slotByNode,
  topLevelAncestorId
} from "../sceneQueries";

describe("scene queries", () => {
  it("finds the first page from the contract fixture", () => {
    expect(firstPageId(minimalScene)).toBe("page_a4");
  });

  it("flattens page node ids in render order", () => {
    expect(flattenPageNodeIds(minimalScene, "page_a4")).toEqual(["node_contact_name"]);
  });

  it("finds a slot bound to a selected node", () => {
    expect(slotByNode(minimalScene, "node_contact_name")?.key).toBe("contact.full_name");
  });

  it("allows direct geometry edits only for unlocked free-positioned nodes", () => {
    const scene = cloneScene();

    expect(isNodeDirectGeometryEditable(scene, "node_contact_name")).toBe(true);

    scene.nodes.node_contact_name.locked = true;
    expect(isNodeDirectGeometryEditable(scene, "node_contact_name")).toBe(false);

    scene.nodes.node_contact_name.locked = false;
    scene.nodes.stack = {
      ...scene.nodes.node_contact_name,
      id: "stack",
      name: "Stack",
      kind: {
        kind: "auto_layout",
        direction: "column",
        wrap: false
      },
      children: ["node_contact_name"]
    };
    scene.pages.page_a4.children = ["stack"];

    expect(isNodeDirectGeometryEditable(scene, "node_contact_name")).toBe(false);
    expect(isNodeDirectGeometryEditable(scene, "missing_node")).toBe(false);
  });

  it("summarizes slot bound nodes with page context", () => {
    const slot = slotByNode(minimalScene, "node_contact_name");

    expect(pageIdForNode(minimalScene, "node_contact_name")).toBe("page_a4");
    expect(slot ? slotBoundNodeSummaries(minimalScene, slot) : []).toEqual([
      {
        nodeId: "node_contact_name",
        nodeName: "Contact Name",
        pageId: "page_a4",
        pageName: "A4 Letter"
      }
    ]);
  });

  it("finds the first rendered node that references an asset", () => {
    const scene = cloneScene();
    scene.nodes.node_logo = {
      ...scene.nodes.node_contact_name,
      id: "node_logo",
      name: "Logo",
      kind: {
        kind: "image",
        asset_id: "asset_logo",
        alt: "Logo"
      },
      source_asset_id: "asset_logo",
      children: []
    };
    scene.nodes.orphan_hero = {
      ...scene.nodes.node_logo,
      id: "orphan_hero",
      name: "Orphan Hero",
      kind: {
        kind: "image",
        asset_id: "asset_hero",
        alt: "Hero"
      },
      source_asset_id: "asset_hero"
    };
    scene.pages.page_a4.children = ["node_logo"];

    expect(nodeIdForAsset(scene, "asset_logo")).toBe("node_logo");
    expect(nodeIdForAsset(scene, "asset_hero")).toBe("orphan_hero");
    expect(nodeIdForAsset(scene, "missing_asset")).toBeNull();
  });

  it("clamps free-positioned page children to page bounds", () => {
    const scene = cloneScene();
    const node = scene.nodes.node_contact_name;

    const clamped = clampNodeTransformToParentBounds(scene, node, {
      ...node.transform,
      x: 1000,
      y: -12
    });

    expect(clamped.x).toBe(50);
    expect(clamped.y).toBe(0);
  });

  it("clamps nested children to their parent frame bounds", () => {
    const scene = cloneScene();
    scene.nodes.node_frame = {
      ...scene.nodes.node_contact_name,
      id: "node_frame",
      name: "Frame",
      kind: {
        kind: "frame"
      },
      size: {
        width: {
          kind: "fixed",
          value: 100
        },
        height: {
          kind: "fixed",
          value: 80
        }
      },
      children: ["node_contact_name"]
    };
    scene.nodes.node_contact_name.size = {
      width: {
        kind: "fixed",
        value: 40
      },
      height: {
        kind: "fixed",
        value: 20
      }
    };
    scene.pages.page_a4.children = ["node_frame"];

    const clamped = clampNodeTransformToParentBounds(scene, scene.nodes.node_contact_name, {
      ...scene.nodes.node_contact_name.transform,
      x: 90,
      y: 90
    });

    expect(clamped.x).toBe(60);
    expect(clamped.y).toBe(60);
  });

  it("resolves the top-level container ancestor for canvas double-click targeting", () => {
    const scene = nestedScene();

    // Deeply nested leaf -> outermost top-level frame.
    expect(topLevelAncestorId(scene, "headline")).toBe("hero");
    // Intermediate container -> still the outermost frame.
    expect(topLevelAncestorId(scene, "inner")).toBe("hero");
    // A node that is already top-level resolves to itself.
    expect(topLevelAncestorId(scene, "hero")).toBe("hero");
    expect(topLevelAncestorId(scene, "sibling")).toBe("sibling");
    // Null / unknown selections.
    expect(topLevelAncestorId(scene, null)).toBeNull();
    expect(topLevelAncestorId(scene, "missing")).toBeNull();
  });

  it("identifies containers that actually hold children", () => {
    const scene = nestedScene();

    expect(isContainerNode(scene.nodes.hero)).toBe(true);
    expect(isContainerNode(scene.nodes.inner)).toBe(true);
    expect(isContainerNode(scene.nodes.headline)).toBe(false); // leaf text
    expect(isContainerNode(scene.nodes.sibling)).toBe(false); // empty frame
  });
});

function cloneScene(): Scene {
  return JSON.parse(JSON.stringify(minimalScene)) as Scene;
}

/**
 * page -> hero(frame) -> inner(group) -> headline(text); plus an empty
 * top-level sibling frame. Exercises multi-level ancestry resolution.
 */
function nestedScene(): Scene {
  const scene = cloneScene();
  const template = scene.nodes.node_contact_name;
  const hero: Node = {
    ...template,
    id: "hero",
    name: "Hero",
    kind: { kind: "frame" },
    children: ["inner"]
  };
  const inner: Node = {
    ...template,
    id: "inner",
    name: "Inner",
    kind: { kind: "group" },
    children: ["headline"]
  };
  const headline: Node = {
    ...template,
    id: "headline",
    name: "Headline",
    kind: { ...template.kind },
    children: []
  };
  const sibling: Node = {
    ...template,
    id: "sibling",
    name: "Sibling",
    kind: { kind: "frame" },
    children: []
  };
  scene.nodes = { hero, inner, headline, sibling };
  scene.pages.page_a4.children = ["hero", "sibling"];
  return scene;
}
