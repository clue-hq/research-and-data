import { describe, expect, it } from "vitest";
import { minimalScene } from "@/fixtures/minimalScene";
import type { Diagnostic, Node, Scene } from "../contracts";
import {
  deriveSelectionChromeModel,
  diagnosticCountsForActivePage,
  diagnosticCountsForSelectedNode,
  selectedBaseObjectKind,
  slotBindingSummaries
} from "../selectionChrome";

describe("selection chrome model", () => {
  it("classifies ordinary text nodes by base object kind", () => {
    const scene = cloneScene();
    scene.slots = {};
    scene.nodes.node_contact_name.computed = computed(24, 32, 180, 30);

    const model = deriveSelectionChromeModel(scene, {
      activePageId: "page_a4",
      selectedNodeId: "node_contact_name"
    });

    expect(model.selectedObjectKind).toBe("text");
    expect(model.baseObjectKind).toBe("text");
    expect(model.isSlotBound).toBe(false);
    expect(model.slotKeys).toEqual([]);
    expect(model.selectionBox).toEqual({
      box: { x: 24, y: 32, width: 180, height: 30 },
      rotation: scene.nodes.node_contact_name.transform.rotation,
      nodeId: "node_contact_name"
    });
  });

  it("keeps slot-bound status separate from the base object kind", () => {
    const scene = cloneScene();
    scene.nodes.node_contact_name.computed = computed(24, 32, 180, 30);

    const model = deriveSelectionChromeModel(scene, {
      activePageId: "page_a4",
      selectedNodeId: "node_contact_name"
    });

    expect(model.selectedObjectKind).toBe("slot_bound");
    expect(model.baseObjectKind).toBe("text");
    expect(model.isSlotBound).toBe(true);
    expect(model.slotKeys).toEqual(["contact.full_name"]);
    expect(model.slotBindings).toEqual([
      {
        id: "slot_contact_name",
        key: "contact.full_name",
        label: "Contact full name",
        contentType: "text_short"
      }
    ]);
  });

  it("sorts slot bindings by key then id for stable overlay and inspector output", () => {
    const scene = cloneScene();
    scene.slots.slot_contact_title = {
      ...scene.slots.slot_contact_name,
      id: "slot_contact_title",
      key: "contact.title",
      label: "Contact title",
      bound_nodes: ["node_contact_name"]
    };
    scene.slots.slot_account_name = {
      ...scene.slots.slot_contact_name,
      id: "slot_account_name",
      key: "account.name",
      label: "Account name",
      bound_nodes: ["node_contact_name"]
    };

    expect(slotBindingSummaries(Object.values(scene.slots)).map((slot) => slot.key)).toEqual([
      "account.name",
      "contact.full_name",
      "contact.title"
    ]);
  });

  it("reports locked and layout-managed direct-edit affordances", () => {
    const lockedScene = cloneScene();
    lockedScene.nodes.node_contact_name.locked = true;
    lockedScene.nodes.node_contact_name.computed = computed(24, 32, 180, 30);

    const lockedModel = deriveSelectionChromeModel(lockedScene, {
      activePageId: "page_a4",
      selectedNodeId: "node_contact_name"
    });

    expect(lockedModel.showHandles).toBe(false);
    expect(lockedModel.disabledReason).toMatch(/locked/i);

    const managedScene = autoLayoutManagedScene();
    const managedModel = deriveSelectionChromeModel(managedScene, {
      activePageId: "page_a4",
      selectedNodeId: "node_contact_name"
    });

    expect(managedModel.showHandles).toBe(false);
    expect(managedModel.disabledReason).toMatch(/auto-layout parent/i);
  });

  it("includes direct node, bound slot, and placed asset diagnostics for a selected node", () => {
    const scene = imageNodeScene();
    const node = scene.nodes.node_image;
    const counts = diagnosticCountsForSelectedNode(scene, node, [
      diagnostic("error", { kind: "node", id: "node_image" }),
      diagnostic("warning", { kind: "slot", id: "slot_contact_name" }),
      diagnostic("warning", { kind: "asset", id: "asset_logo" }),
      diagnostic("error", { kind: "page", id: "page_a4" }),
      diagnostic("advice", { kind: "node", id: "node_image" })
    ]);

    expect(counts).toEqual({ errors: 1, warnings: 2 });
  });

  it("counts active artboard diagnostics when no node is selected", () => {
    const scene = cloneScene();
    scene.nodes.node_contact_name.computed = computed(24, 32, 180, 30);
    const diagnostics: Diagnostic[] = [
      diagnostic("error", { kind: "page", id: "page_a4" }),
      diagnostic("warning", { kind: "node", id: "node_contact_name" }),
      diagnostic("warning", { kind: "slot", id: "slot_contact_name" }),
      diagnostic("warning", { kind: "document" })
    ];

    expect(diagnosticCountsForActivePage(scene, "page_a4", diagnostics)).toEqual({
      errors: 1,
      warnings: 2
    });

    const model = deriveSelectionChromeModel(scene, {
      activePageId: "page_a4",
      selectedNodeId: null,
      diagnostics
    });

    expect(model.selectedObjectKind).toBe("artboard");
    expect(model.diagnosticCounts).toEqual({ errors: 1, warnings: 2 });
  });

  it("classifies supported node kinds for inspector parity", () => {
    const template = cloneScene().nodes.node_contact_name;
    expect(selectedBaseObjectKind(nodeWithKind(template, { kind: "frame" }))).toBe("frame");
    expect(selectedBaseObjectKind(nodeWithKind(template, { kind: "group" }))).toBe("group");
    expect(selectedBaseObjectKind(nodeWithKind(template, { kind: "auto_layout", direction: "row", wrap: false }))).toBe(
      "auto_layout"
    );
    expect(selectedBaseObjectKind(nodeWithKind(template, { kind: "image", asset_id: "asset_logo", alt: null }))).toBe(
      "image"
    );
    expect(selectedBaseObjectKind(nodeWithKind(template, { kind: "rect" }))).toBe("shape");
    expect(selectedBaseObjectKind(nodeWithKind(template, { kind: "vector", path_data: "M0 0 L1 1" }))).toBe("shape");
  });
});

function cloneScene(): Scene {
  return JSON.parse(JSON.stringify(minimalScene)) as Scene;
}

function computed(x: number, y: number, width: number, height: number) {
  const bounds = { x, y, width, height };
  return { layout_bounds: bounds, render_bounds: bounds };
}

function diagnostic(severity: Diagnostic["severity"], subject: Diagnostic["subject"]): Diagnostic {
  return {
    severity,
    phase: "validation",
    code: `TEST_${severity}`,
    message: `${severity} diagnostic`,
    subject,
    hint: null
  };
}

function autoLayoutManagedScene(): Scene {
  const scene = cloneScene();
  const template = scene.nodes.node_contact_name;
  const stack: Node = {
    ...template,
    id: "node_stack",
    name: "Stack",
    kind: { kind: "auto_layout", direction: "column", wrap: false },
    children: ["node_contact_name"],
    locked: false,
    computed: computed(10, 20, 240, 120)
  };
  scene.nodes.node_contact_name = {
    ...scene.nodes.node_contact_name,
    locked: false,
    computed: computed(24, 32, 180, 30)
  };
  scene.nodes.node_stack = stack;
  scene.pages.page_a4.children = ["node_stack"];
  return scene;
}

function imageNodeScene(): Scene {
  const scene = cloneScene();
  const imageNode: Node = {
    ...scene.nodes.node_contact_name,
    id: "node_image",
    name: "Logo",
    kind: { kind: "image", asset_id: "asset_logo", alt: "Logo" },
    source_asset_id: "asset_logo",
    children: [],
    computed: computed(24, 32, 120, 120)
  };
  scene.nodes = { node_image: imageNode };
  scene.pages.page_a4.children = ["node_image"];
  scene.slots.slot_contact_name.bound_nodes = ["node_image"];
  return scene;
}

function nodeWithKind(template: Node, kind: Node["kind"]): Node {
  return {
    ...template,
    kind
  };
}
