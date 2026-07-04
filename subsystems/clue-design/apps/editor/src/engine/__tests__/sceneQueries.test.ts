import { describe, expect, it } from "vitest";
import { minimalScene } from "@/fixtures/minimalScene";
import type { Scene } from "../contracts";
import type { Node } from "../contracts";
import {
  canAlignNodes,
  canDistributeNodes,
  canGroupNodes,
  canUngroupNode,
  clampNodeTransformToParentBounds,
  firstPageId,
  flattenPageNodeIds,
  isContainerNode,
  isNodeDirectGeometryEditable,
  isNodeFreezableOnGesture,
  nodeIdForAsset,
  nodePageSpaceBox,
  pageIdForNode,
  siblingArrangeInfo,
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

  describe("isNodeFreezableOnGesture (handoff-absolute lazy seam)", () => {
    it("is true only for a node blocked solely by Stack solver ownership", () => {
      const scene = cloneScene();
      scene.nodes.stack = {
        ...scene.nodes.node_contact_name,
        id: "stack",
        name: "Stack",
        kind: { kind: "auto_layout", direction: "column", wrap: false },
        children: ["node_contact_name"]
      };
      scene.pages.page_a4.children = ["stack"];

      // Blocked, and a freeze would fix it (Stack-managed, not freehand).
      expect(isNodeFreezableOnGesture(scene, "node_contact_name")).toBe(true);
    });

    it("is false for a node that is already directly geometry-editable", () => {
      const scene = cloneScene();
      // No auto-layout ancestor: already free.
      expect(isNodeDirectGeometryEditable(scene, "node_contact_name")).toBe(true);
      expect(isNodeFreezableOnGesture(scene, "node_contact_name")).toBe(false);
    });

    it("is false for a locked node even under a Stack parent (freeze cannot fix locking)", () => {
      const scene = cloneScene();
      scene.nodes.stack = {
        ...scene.nodes.node_contact_name,
        id: "stack",
        name: "Stack",
        kind: { kind: "auto_layout", direction: "column", wrap: false },
        children: ["node_contact_name"]
      };
      scene.pages.page_a4.children = ["stack"];
      scene.nodes.node_contact_name.locked = true;

      expect(isNodeFreezableOnGesture(scene, "node_contact_name")).toBe(false);
    });

    it("is false for a freehand child of a Free auto-layout container (already editable)", () => {
      const scene = cloneScene();
      scene.nodes.stack = {
        ...scene.nodes.node_contact_name,
        id: "stack",
        name: "Free container",
        kind: { kind: "auto_layout", direction: "column", wrap: false },
        layout: { gap: 0, grow: 0, padding: [0, 0, 0, 0], layout_mode: "free" },
        children: ["node_contact_name"]
      };
      scene.pages.page_a4.children = ["stack"];

      expect(isNodeDirectGeometryEditable(scene, "node_contact_name")).toBe(true);
      expect(isNodeFreezableOnGesture(scene, "node_contact_name")).toBe(false);
    });

    it("is false for a null/missing node id", () => {
      const scene = cloneScene();
      expect(isNodeFreezableOnGesture(scene, null)).toBe(false);
      expect(isNodeFreezableOnGesture(scene, "missing_node")).toBe(false);
    });
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

  describe("arrange (Phase 4b): z-order + group/ungroup gating", () => {
    it("reports front/back position among page-level siblings", () => {
      const scene = siblingScene();

      expect(siblingArrangeInfo(scene, "a")).toEqual({
        siblings: ["a", "b", "c"],
        index: 0,
        isFront: false,
        isBack: true
      });
      expect(siblingArrangeInfo(scene, "b")).toEqual({
        siblings: ["a", "b", "c"],
        index: 1,
        isFront: false,
        isBack: false
      });
      expect(siblingArrangeInfo(scene, "c")).toEqual({
        siblings: ["a", "b", "c"],
        index: 2,
        isFront: true,
        isBack: false
      });
      expect(siblingArrangeInfo(scene, null)).toBeNull();
      expect(siblingArrangeInfo(scene, "missing")).toBeNull();
    });

    it("allows grouping 2+ unlocked same-parent siblings", () => {
      const scene = siblingScene();
      expect(canGroupNodes(scene, ["a", "b"])).toBe(true);
      expect(canGroupNodes(scene, ["a", "b", "c"])).toBe(true);
    });

    it("rejects grouping fewer than two nodes", () => {
      const scene = siblingScene();
      expect(canGroupNodes(scene, [])).toBe(false);
      expect(canGroupNodes(scene, ["a"])).toBe(false);
    });

    it("rejects grouping duplicate ids", () => {
      const scene = siblingScene();
      expect(canGroupNodes(scene, ["a", "a"])).toBe(false);
    });

    it("rejects grouping a locked member", () => {
      const scene = siblingScene();
      scene.nodes.b.locked = true;
      expect(canGroupNodes(scene, ["a", "b"])).toBe(false);
    });

    it("rejects grouping a missing node id", () => {
      const scene = siblingScene();
      expect(canGroupNodes(scene, ["a", "missing"])).toBe(false);
    });

    it("rejects grouping nodes with different parents", () => {
      const scene = siblingScene();
      scene.nodes.frame = {
        ...scene.nodes.a,
        id: "frame",
        name: "Frame",
        kind: { kind: "frame" },
        children: ["c"]
      };
      scene.nodes.c = { ...scene.nodes.c };
      scene.pages.page_a4.children = ["a", "b", "frame"];
      // "c" is now a child of "frame", not a page-level sibling of a/b.
      expect(canGroupNodes(scene, ["a", "c"])).toBe(false);
    });

    it("rejects grouping solver-managed stack children (not freehand)", () => {
      const scene = siblingScene();
      scene.nodes.stack = {
        ...scene.nodes.a,
        id: "stack",
        name: "Stack",
        kind: { kind: "auto_layout", direction: "column", wrap: false },
        children: ["a", "b"]
      };
      scene.pages.page_a4.children = ["stack"];
      expect(canGroupNodes(scene, ["a", "b"])).toBe(false);
    });

    it("allows grouping freehand children of a Free auto-layout container", () => {
      const scene = siblingScene();
      scene.nodes.stack = {
        ...scene.nodes.a,
        id: "stack",
        name: "Free container",
        kind: { kind: "auto_layout", direction: "column", wrap: false },
        layout: { gap: 0, grow: 0, padding: [0, 0, 0, 0], layout_mode: "free" },
        children: ["a", "b"]
      };
      scene.pages.page_a4.children = ["stack"];
      expect(canGroupNodes(scene, ["a", "b"])).toBe(true);
    });

    it("allows ungrouping an unlocked Frame or Group container", () => {
      const scene = nestedScene();
      expect(canUngroupNode(scene, "hero")).toBe(true); // frame
      expect(canUngroupNode(scene, "inner")).toBe(true); // group
    });

    it("rejects ungrouping a leaf, a locked container, or a null selection", () => {
      const scene = nestedScene();
      expect(canUngroupNode(scene, "headline")).toBe(false); // leaf text
      scene.nodes.hero.locked = true;
      expect(canUngroupNode(scene, "hero")).toBe(false);
      expect(canUngroupNode(scene, null)).toBe(false);
      expect(canUngroupNode(scene, "missing")).toBe(false);
    });
  });

  describe("align/distribute eligibility (Phase 4b-3)", () => {
    it("allows Align at 2+ direct-geometry-editable nodes", () => {
      const scene = siblingScene();
      expect(canAlignNodes(scene, ["a", "b"])).toBe(true);
      expect(canAlignNodes(scene, ["a", "b", "c"])).toBe(true);
    });

    it("rejects Align under 2 nodes", () => {
      const scene = siblingScene();
      expect(canAlignNodes(scene, [])).toBe(false);
      expect(canAlignNodes(scene, ["a"])).toBe(false);
    });

    it("rejects Align when any selected node is locked", () => {
      const scene = siblingScene();
      scene.nodes.b.locked = true;
      expect(canAlignNodes(scene, ["a", "b"])).toBe(false);
    });

    it("rejects Align when any selected node is a solver-managed stack child", () => {
      const scene = siblingScene();
      scene.nodes.stack = {
        ...scene.nodes.a,
        id: "stack",
        name: "Stack",
        kind: { kind: "auto_layout", direction: "column", wrap: false },
        children: ["a", "b"]
      };
      scene.pages.page_a4.children = ["stack"];
      expect(canAlignNodes(scene, ["a", "b"])).toBe(false);
    });

    it("allows Align for freehand children of a Free auto-layout container", () => {
      const scene = siblingScene();
      scene.nodes.stack = {
        ...scene.nodes.a,
        id: "stack",
        name: "Free container",
        kind: { kind: "auto_layout", direction: "column", wrap: false },
        layout: { gap: 0, grow: 0, padding: [0, 0, 0, 0], layout_mode: "free" },
        children: ["a", "b"]
      };
      scene.pages.page_a4.children = ["stack"];
      expect(canAlignNodes(scene, ["a", "b"])).toBe(true);
    });

    it("rejects Align when any selected node id is missing", () => {
      const scene = siblingScene();
      expect(canAlignNodes(scene, ["a", "missing"])).toBe(false);
    });

    it("allows Distribute at 3+ direct-geometry-editable nodes, rejects under 3", () => {
      const scene = siblingScene();
      expect(canDistributeNodes(scene, ["a", "b", "c"])).toBe(true);
      expect(canDistributeNodes(scene, ["a", "b"])).toBe(false);
    });

    it("rejects Distribute when any selected node is locked", () => {
      const scene = siblingScene();
      scene.nodes.c.locked = true;
      expect(canDistributeNodes(scene, ["a", "b", "c"])).toBe(false);
    });

    it("reads a pinned node's absolute_box as its page-space box", () => {
      const scene = siblingScene();
      scene.nodes.a.position_mode = "absolute";
      scene.nodes.a.absolute_box = { x: 10, y: 20, width: 30, height: 40 };
      expect(nodePageSpaceBox(scene, "a")).toEqual({ x: 10, y: 20, width: 30, height: 40 });
    });

    it("falls back to computed.layout_bounds for a boxless pin", () => {
      const scene = siblingScene();
      scene.nodes.a.position_mode = "absolute";
      scene.nodes.a.absolute_box = null;
      scene.nodes.a.computed = {
        layout_bounds: { x: 1, y: 2, width: 3, height: 4 },
        render_bounds: { x: 1, y: 2, width: 3, height: 4 }
      };
      expect(nodePageSpaceBox(scene, "a")).toEqual({ x: 1, y: 2, width: 3, height: 4 });
    });

    it("reads a non-pinned node's computed.layout_bounds as its page-space box", () => {
      const scene = siblingScene();
      scene.nodes.b.computed = {
        layout_bounds: { x: 5, y: 6, width: 7, height: 8 },
        render_bounds: { x: 5, y: 6, width: 7, height: 8 }
      };
      expect(nodePageSpaceBox(scene, "b")).toEqual({ x: 5, y: 6, width: 7, height: 8 });
    });

    it("returns null for a node with no resolvable box or a missing node", () => {
      const scene = siblingScene();
      scene.nodes.a.computed = null;
      expect(nodePageSpaceBox(scene, "a")).toBeNull();
      expect(nodePageSpaceBox(scene, "missing")).toBeNull();
    });
  });
});

/** page -> three unlocked, unmanaged page-level siblings a, b, c (in that
 * z-order) — the minimal fixture for arrange (z-order + group) tests. */
function siblingScene(): Scene {
  const scene = cloneScene();
  const template = scene.nodes.node_contact_name;
  const a: Node = { ...template, id: "a", name: "A", kind: { kind: "rect" }, children: [] };
  const b: Node = { ...template, id: "b", name: "B", kind: { kind: "rect" }, children: [] };
  const c: Node = { ...template, id: "c", name: "C", kind: { kind: "rect" }, children: [] };
  scene.nodes = { a, b, c };
  scene.pages.page_a4.children = ["a", "b", "c"];
  return scene;
}

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
