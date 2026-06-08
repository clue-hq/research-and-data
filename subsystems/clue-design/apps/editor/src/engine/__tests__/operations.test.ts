import { describe, expect, it } from "vitest";
import { minimalScene } from "@/fixtures/minimalScene";
import type { AssetRecord, ComputedGeometry, Node, Scene } from "../contracts";
import { localEditorEngine } from "../editorEngine";
import {
  defaultTextSlot,
  nodePatch,
  set,
  updateNodeLocked,
  updateNodeTransform,
  updateNodeTransformAndSize
} from "../operations";

function cloneScene(): Scene {
  return JSON.parse(JSON.stringify(minimalScene)) as Scene;
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

  it("upserts slots without reinterpreting slot semantics", () => {
    const scene = cloneScene();
    const slot = defaultTextSlot("node_contact_name", "contact.title", "Contact title", "Chief Medical Officer");
    const result = localEditorEngine.applyOperation(scene, {
      kind: "upsert_slot",
      slot
    });

    expect(result.accepted).toBe(true);
    expect(result.scene.slots.slot_contact_title.key).toBe("contact.title");
    expect(result.scene.slots.slot_contact_title.bound_nodes).toEqual(["node_contact_name"]);
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
});
