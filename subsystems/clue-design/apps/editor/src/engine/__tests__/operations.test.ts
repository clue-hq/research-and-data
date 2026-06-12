import { describe, expect, it } from "vitest";
import { minimalScene } from "@/fixtures/minimalScene";
import type { AssetRecord, ComputedGeometry, Node, Scene } from "../contracts";
import { localEditorEngine } from "../editorEngine";
import {
  addPage,
  defaultTextSlot,
  insertNode,
  moveNodeToParent,
  nodePatch,
  removeExportProfile,
  removeNode,
  removePage,
  set,
  slotIdFromKey,
  updateAutoLayoutAlignment,
  updateAutoLayoutNode,
  updateNodeLayout,
  updateNodeLocked,
  updateNodeTransform,
  updateNodeTransformAndSize,
  updatePageSize,
  updateTextNode,
  upsertExportProfile
} from "../operations";

function cloneScene(): Scene {
  return JSON.parse(JSON.stringify(minimalScene)) as Scene;
}

function computedGeometry(x: number, y: number, width: number, height: number): ComputedGeometry {
  return {
    layout_bounds: {
      x,
      y,
      width,
      height
    },
    render_bounds: {
      x,
      y,
      width,
      height
    }
  };
}

function generatedAsset(): AssetRecord {
  return {
    id: "asset_generated_hero",
    label: "Generated clinic hero",
    kind: "raster_image",
    status: "ready",
    source: {
      kind: "generated",
      request_id: "gen_hero_1",
      model: "mock-image-model"
    },
    media: {
      mime_type: "image/png",
      filename: "generated-clinic-hero.png",
      byte_length: 8192,
      digest: null,
      location: null
    },
    raster: {
      pixel_width: 1600,
      pixel_height: 900,
      dpi_x: 144,
      dpi_y: 144,
      has_alpha: false,
      color_profile: "srgb",
      aspect_ratio: 1.7777777778
    },
    vector: null,
    font: null,
    logo: null,
    license: {
      name: "generated_commercial_use",
      allow_export: true,
      allow_modification: true,
      allow_embedding: true,
      allow_subsetting: false,
      source_url: null,
      restrictions: []
    },
    provenance: {
      created_by: "agent",
      created_at: "2026-06-08T00:00:00Z",
      source_label: "image generation",
      confidence: 0.82,
      notes: ["Generated from campaign prompt."]
    },
    tags: ["generated", "hero"]
  };
}

const printPdfProfile = {
  name: "client_print_pdf",
  format: "pdf" as const,
  pdf_intent: "print" as const,
  raster: null,
  include_bleed: true,
  embed_fonts: true
};

function assetPlaceholderNode(): Node {
  return {
    id: "node_hero_image",
    name: "Hero image",
    kind: {
      kind: "rect"
    },
    transform: {
      x: 24,
      y: 76,
      rotation: 0,
      skew_x: 0,
      skew_y: 0,
      flip_x: false,
      flip_y: false
    },
    size: {
      width: {
        kind: "fixed",
        value: 120
      },
      height: {
        kind: "fixed",
        value: 67.5
      }
    },
    children: [],
    fills: [],
    strokes: [],
    corner: {
      top_left: 0,
      top_right: 0,
      bottom_right: 0,
      bottom_left: 0
    },
    opacity: 1,
    source_asset_id: null,
    asset_placement: null,
    clip: false,
    layout: null,
    computed: null,
    locked: false
  };
}

describe("local editor engine", () => {
  it("applies editor-generated update node operations optimistically", () => {
    const scene = cloneScene();
    const node = scene.nodes.node_contact_name;
    const operation = updateNodeTransform(node, {
      ...node.transform,
      x: 42
    });

    expect(operation.kind).toBe("update_node");
    if (operation.kind !== "update_node") {
      throw new Error("expected update_node operation");
    }

    expect(operation.patch).toMatchObject({
      name: { kind: "unchanged" },
      kind: { kind: "unchanged" },
      transform: { kind: "set" },
      size: { kind: "unchanged" },
      fills: { kind: "unchanged" },
      strokes: { kind: "unchanged" },
      corner: { kind: "unchanged" },
      opacity: { kind: "unchanged" },
      opacity_token: { kind: "unchanged" },
      source_asset_id: { kind: "unchanged" },
      asset_placement: { kind: "unchanged" },
      clip: { kind: "unchanged" },
      layout: { kind: "unchanged" },
      computed: { kind: "unchanged" },
      locked: { kind: "unchanged" }
    });

    const result = localEditorEngine.applyOperation(
      scene,
      operation
    );

    expect(result.accepted).toBe(true);
    expect(result.scene.nodes.node_contact_name.transform.x).toBe(42);
    expect(scene.nodes.node_contact_name.transform.x).toBe(24);
  });

  it("rejects geometry edits to locked nodes but allows unlock toggles", () => {
    const scene = cloneScene();
    const locked = localEditorEngine.applyOperation(scene, updateNodeLocked(scene.nodes.node_contact_name, true));

    expect(locked.accepted).toBe(true);
    const rejected = localEditorEngine.applyOperation(
      locked.scene,
      updateNodeTransform(locked.scene.nodes.node_contact_name, {
        ...locked.scene.nodes.node_contact_name.transform,
        x: 80
      })
    );

    expect(rejected.accepted).toBe(false);
    expect(rejected.scene.nodes.node_contact_name.transform.x).toBe(24);

    const unlocked = localEditorEngine.applyOperation(
      locked.scene,
      updateNodeLocked(locked.scene.nodes.node_contact_name, false)
    );

    expect(unlocked.accepted).toBe(true);
    expect(unlocked.scene.nodes.node_contact_name.locked).toBe(false);
  });

  it("applies transform and size from a single resize operation", () => {
    const scene = cloneScene();
    const node = scene.nodes.node_contact_name;
    const result = localEditorEngine.applyOperation(
      scene,
      updateNodeTransformAndSize(
        node,
        {
          ...node.transform,
          x: 36,
          rotation: 8
        },
        {
          width: {
            kind: "fixed",
            value: 120
          },
          height: {
            kind: "fixed",
            value: 32
          }
        }
      )
    );

    expect(result.accepted).toBe(true);
    expect(result.scene.nodes.node_contact_name.transform.x).toBe(36);
    expect(result.scene.nodes.node_contact_name.transform.rotation).toBe(8);
    expect(result.scene.nodes.node_contact_name.size.width).toEqual({
      kind: "fixed",
      value: 120
    });
  });

  it("inserts nodes through the canonical operation shape", () => {
    const scene = cloneScene();
    const node: Node = {
      ...JSON.parse(JSON.stringify(scene.nodes.node_contact_name)),
      id: "node_inserted_contact",
      name: "Inserted Contact",
      children: [],
      computed: null
    };

    const result = localEditorEngine.applyOperation(
      scene,
      insertNode({ kind: "page", id: "page_a4" }, 1, node)
    );

    expect(result.accepted).toBe(true);
    expect(result.scene.pages.page_a4.children).toEqual([
      "node_contact_name",
      "node_inserted_contact"
    ]);
    expect(result.scene.nodes.node_inserted_contact).toMatchObject({
      id: "node_inserted_contact",
      name: "Inserted Contact"
    });
    expect(scene.nodes.node_inserted_contact).toBeUndefined();

    const rejected = localEditorEngine.applyOperation(
      result.scene,
      insertNode({ kind: "page", id: "missing_page" }, 0, {
        ...node,
        id: "node_missing_parent"
      })
    );

    expect(rejected.accepted).toBe(false);
    expect(rejected.message).toContain("Missing parent missing_page");
  });

  it("accepts core-compatible parent refs that use id", () => {
    const scene = cloneScene();
    scene.pages.page_a4.children = [];
    const result = localEditorEngine.applyOperation(scene, {
      kind: "move_node",
      node_id: "node_contact_name",
      new_parent: {
        kind: "page",
        id: "page_a4"
      },
      index: 0
    });

    expect(result.accepted).toBe(true);
    expect(result.scene.pages.page_a4.children).toEqual(["node_contact_name"]);
  });

  it("rejects move operations that would corrupt the scene tree", () => {
    const scene = cloneScene();
    scene.nodes.node_frame = {
      ...scene.nodes.node_contact_name,
      id: "node_frame",
      name: "Frame",
      kind: {
        kind: "frame"
      },
      children: ["node_contact_name"],
      locked: false
    };
    scene.nodes.node_contact_name.children = [];
    scene.nodes.node_cta = {
      ...scene.nodes.node_contact_name,
      id: "node_cta",
      name: "CTA",
      children: []
    };
    scene.pages.page_a4.children = ["node_frame", "node_cta"];

    const leafParent = localEditorEngine.applyOperation(
      scene,
      moveNodeToParent("node_cta", { kind: "node", id: "node_contact_name" }, 0)
    );
    expect(leafParent.accepted).toBe(false);
    expect(leafParent.message).toContain("cannot contain children");

    const descendantParent = localEditorEngine.applyOperation(
      scene,
      moveNodeToParent("node_frame", { kind: "node", id: "node_contact_name" }, 0)
    );
    expect(descendantParent.accepted).toBe(false);
    expect(descendantParent.message).toContain("itself or its descendant");

    scene.nodes.node_frame.locked = true;
    const lockedParent = localEditorEngine.applyOperation(
      scene,
      moveNodeToParent("node_cta", { kind: "node", id: "node_frame" }, 0)
    );
    expect(lockedParent.accepted).toBe(false);
    expect(lockedParent.message).toContain("Parent node node_frame is locked");

    const invalidIndex = localEditorEngine.applyOperation(
      scene,
      moveNodeToParent("node_cta", { kind: "page", id: "page_a4" }, -1)
    );
    expect(invalidIndex.accepted).toBe(false);
    expect(invalidIndex.message).toContain("Invalid insertion index");

    expect(scene.pages.page_a4.children).toEqual(["node_frame", "node_cta"]);
    expect(scene.nodes.node_frame.children).toEqual(["node_contact_name"]);
  });

  it("mirrors core computed geometry field names in node patches", () => {
    const computed: ComputedGeometry = {
      layout_bounds: {
        x: 0,
        y: 0,
        width: 10,
        height: 12
      },
      render_bounds: {
        x: 0,
        y: 0,
        width: 10,
        height: 12
      }
    };

    expect(nodePatch({ computed: set(computed) }).computed).toEqual({
      kind: "set",
      value: computed
    });
  });

  it("invalidates stale computed geometry after local geometry edits", () => {
    const scene = cloneScene();
    scene.nodes.node_contact_name.computed = computedGeometry(24, 40, 320, 48);

    const result = localEditorEngine.applyOperation(
      scene,
      updateNodeTransform(scene.nodes.node_contact_name, {
        ...scene.nodes.node_contact_name.transform,
        x: 80
      })
    );

    expect(result.accepted).toBe(true);
    expect(result.scene.nodes.node_contact_name.transform.x).toBe(80);
    expect(result.scene.nodes.node_contact_name.computed).toBeNull();
  });

  it("keeps canonical computed geometry when a patch explicitly sets it", () => {
    const scene = cloneScene();
    const computed = computedGeometry(12, 18, 240, 44);

    const result = localEditorEngine.applyOperation(scene, {
      kind: "update_node",
      node_id: "node_contact_name",
      patch: nodePatch({
        computed: set(computed)
      })
    });

    expect(result.accepted).toBe(true);
    expect(result.scene.nodes.node_contact_name.computed).toEqual(computed);
  });

  it("invalidates page computed geometry when a custom page size changes", () => {
    const scene = cloneScene();
    scene.nodes.node_contact_name.computed = computedGeometry(24, 40, 320, 48);
    const page = scene.pages.page_a4;

    const result = localEditorEngine.applyOperation(
      scene,
      updatePageSize(page, {
        ...page.size,
        width: 1200,
        height: 628,
        unit: "px",
        preset: "custom"
      })
    );

    expect(result.accepted).toBe(true);
    expect(result.scene.pages.page_a4.size).toMatchObject({
      width: 1200,
      height: 628,
      unit: "px",
      preset: "custom"
    });
    expect(result.scene.nodes.node_contact_name.computed).toBeNull();
  });

  it("updates page size through the canonical page patch shape", () => {
    const scene = cloneScene();
    const page = scene.pages.page_a4;
    const result = localEditorEngine.applyOperation(
      scene,
      updatePageSize(page, {
        ...page.size,
        width: 1080,
        height: 1080,
        unit: "px",
        preset: "custom",
        orientation: "landscape"
      })
    );

    expect(result.accepted).toBe(true);
    expect(result.scene.pages.page_a4.size).toMatchObject({
      width: 1080,
      height: 1080,
      unit: "px",
      preset: "custom"
    });
  });

  it("adds and removes custom pages through canonical page operations", () => {
    const scene = cloneScene();
    const customPage = {
      id: "page_square_ad",
      name: "Square Ad",
      size: {
        width: 1080,
        height: 1080,
        unit: "px" as const,
        preset: "custom" as const,
        orientation: "portrait" as const
      },
      children: [] as string[],
      bleed: null,
      safe_area: null,
      background: []
    };

    const added = localEditorEngine.applyOperation(scene, addPage(customPage));
    expect(added.accepted).toBe(true);
    expect(added.scene.pages.page_square_ad.size).toMatchObject({
      width: 1080,
      height: 1080,
      unit: "px",
      preset: "custom"
    });

    const duplicate = localEditorEngine.applyOperation(added.scene, addPage(customPage));
    expect(duplicate.accepted).toBe(false);
    expect(duplicate.message).toContain("already exists");

    added.scene.nodes.node_custom_child = {
      ...added.scene.nodes.node_contact_name,
      id: "node_custom_child",
      children: []
    };
    added.scene.pages.page_square_ad.children = ["node_custom_child"];

    const removed = localEditorEngine.applyOperation(added.scene, removePage("page_square_ad"));
    expect(removed.accepted).toBe(true);
    expect(removed.scene.pages.page_square_ad).toBeUndefined();
    expect(removed.scene.nodes.node_custom_child).toBeUndefined();
  });

  it("emits layout alignment updates as node layout patches", () => {
    const scene = cloneScene();
    const node = scene.nodes.node_contact_name;
    const result = localEditorEngine.applyOperation(
      scene,
      updateAutoLayoutAlignment(node, "center", "start")
    );

    expect(result.accepted).toBe(true);
    expect(result.scene.nodes.node_contact_name.layout?.align_x).toBe("center");
    expect(result.scene.nodes.node_contact_name.layout?.align_y).toBe("start");

    const cleared = localEditorEngine.applyOperation(
      result.scene,
      updateNodeLayout(result.scene.nodes.node_contact_name, null)
    );
    expect(cleared.accepted).toBe(true);
    expect(cleared.scene.nodes.node_contact_name.layout).toBeNull();
  });

  it("updates auto-layout node direction and wrap through the kind patch", () => {
    const scene = cloneScene();
    scene.nodes.node_stack = {
      ...scene.nodes.node_contact_name,
      id: "node_stack",
      kind: {
        kind: "auto_layout",
        direction: "column",
        wrap: false
      },
      children: []
    };
    const result = localEditorEngine.applyOperation(
      scene,
      updateAutoLayoutNode(scene.nodes.node_stack, {
        direction: "row",
        wrap: true
      })
    );

    expect(result.accepted).toBe(true);
    expect(result.scene.nodes.node_stack.kind).toMatchObject({
      kind: "auto_layout",
      direction: "row",
      wrap: true
    });
  });

  it("updates Phase B text metrics through the text node patch", () => {
    const scene = cloneScene();
    const node = scene.nodes.node_contact_name;
    const result = localEditorEngine.applyOperation(
      scene,
      updateTextNode(node, {
        line_height: 1.08,
        letter_spacing: -0.25,
        max_lines: 2,
        wrap: "wrap",
        direction: "auto"
      })
    );

    expect(result.accepted).toBe(true);
    expect(result.scene.nodes.node_contact_name.kind).toMatchObject({
      kind: "text",
      line_height: 1.08,
      letter_spacing: -0.25,
      max_lines: 2,
      wrap: "wrap",
      direction: "auto"
    });
  });

  it("upserts slots without reinterpreting slot semantics", () => {
    const scene = cloneScene();
    const slot = defaultTextSlot("node_contact_name", "contact.title", "Contact title", "Chief Medical Officer");
    const slotId = slotIdFromKey("contact.title");
    const result = localEditorEngine.applyOperation(scene, {
      kind: "upsert_slot",
      slot
    });

    expect(result.accepted).toBe(true);
    expect(result.scene.slots[slotId].key).toBe("contact.title");
    expect(result.scene.slots[slotId].bound_nodes).toEqual(["node_contact_name"]);
  });

  it("derives deterministic collision-free editor slot ids", () => {
    const dotted = slotIdFromKey("account.name");
    const underscored = slotIdFromKey("account_name");

    expect(dotted).toMatch(/^slot_account_name_[0-9a-f]{16}$/);
    expect(underscored).toMatch(/^slot_account_name_[0-9a-f]{16}$/);
    expect(dotted).not.toBe(underscored);
    expect(slotIdFromKey("account.name")).toBe(dotted);
  });

  it("applies asset registry and placement operations without redefining core semantics", () => {
    const scene = cloneScene();
    scene.nodes.node_hero_image = assetPlaceholderNode();
    scene.pages.page_a4.children.push("node_hero_image");

    const withAsset = localEditorEngine.applyOperation(scene, {
      kind: "upsert_asset",
      asset: generatedAsset()
    });
    expect(withAsset.accepted).toBe(true);
    expect(withAsset.scene.assets.asset_generated_hero.kind).toBe("raster_image");

    const placed = localEditorEngine.applyOperation(withAsset.scene, {
      kind: "place_asset_in_node",
      node_id: "node_hero_image",
      asset_id: "asset_generated_hero",
      placement: {
        fit: "cover",
        focal_point: {
          x: 0.5,
          y: 0.42
        },
        preserve_transparency: false,
        alt_text: "Generated clinic hero"
      }
    });

    expect(placed.accepted).toBe(true);
    expect(placed.scene.nodes.node_hero_image.kind).toEqual({
      kind: "image",
      asset_id: "asset_generated_hero",
      alt: "Generated clinic hero"
    });
    expect(placed.scene.nodes.node_hero_image.asset_placement?.fit).toBe("cover");

    const rejectedRemoval = localEditorEngine.applyOperation(placed.scene, {
      kind: "remove_asset",
      asset_id: "asset_generated_hero"
    });
    expect(rejectedRemoval.accepted).toBe(false);
    expect(rejectedRemoval.message).toContain("while referenced");
  });

  it("applies export profile operations as canonical scene data", () => {
    const scene = cloneScene();
    scene.export_profiles = [];
    const withProfile = localEditorEngine.applyOperation(scene, upsertExportProfile(printPdfProfile));

    expect(withProfile.accepted).toBe(true);
    expect(withProfile.scene.export_profiles).toEqual([printPdfProfile]);

    const updatedProfile = {
      ...printPdfProfile,
      include_bleed: false
    };
    const withUpdatedProfile = localEditorEngine.applyOperation(withProfile.scene, upsertExportProfile(updatedProfile));

    expect(withUpdatedProfile.accepted).toBe(true);
    expect(withUpdatedProfile.scene.export_profiles).toEqual([updatedProfile]);

    const removedProfile = localEditorEngine.applyOperation(
      withUpdatedProfile.scene,
      removeExportProfile(printPdfProfile.name)
    );

    expect(removedProfile.accepted).toBe(true);
    expect(removedProfile.scene.export_profiles).toEqual([]);
  });

  it("removes nodes recursively and cleans slot bindings", () => {
    const scene = cloneScene();
    scene.nodes.node_child = {
      ...scene.nodes.node_contact_name,
      id: "node_child",
      name: "Nested Child",
      children: []
    };
    scene.nodes.node_contact_name.children = ["node_child"];
    scene.slots.slot_contact_name.bound_nodes = ["node_contact_name", "node_child"];

    const removed = localEditorEngine.applyOperation(scene, removeNode("node_contact_name"));

    expect(removed.accepted).toBe(true);
    expect(removed.scene.pages.page_a4.children).toEqual([]);
    expect(removed.scene.nodes.node_contact_name).toBeUndefined();
    expect(removed.scene.nodes.node_child).toBeUndefined();
    expect(removed.scene.slots.slot_contact_name.bound_nodes).toEqual([]);
  });
});
