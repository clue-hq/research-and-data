// @vitest-environment node
import { beforeAll, describe, expect, it } from "vitest";

import { minimalScene } from "@/fixtures/minimalScene";
import type { AssetRecord, ComputedGeometry, Node, Scene } from "../contracts";
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
import { WasmEngine, type WasmModule } from "../wasmEngine";
import { loadWasmModuleFromDisk, wasmArtifactPresent } from "../../test/wasmModule";

/**
 * W4 mirror retirement: every operation-application behavior the deleted
 * TS mirror (`localEditorEngine`) was tested for, asserted through the
 * REAL engine instead. lumen-core is authoritative; where the mirror's
 * error strings differed, these tests assert acceptance/rejection and
 * resulting state, not mirror prose.
 */

function cloneScene(): Scene {
  return JSON.parse(JSON.stringify(minimalScene)) as Scene;
}

function computedGeometry(x: number, y: number, width: number, height: number): ComputedGeometry {
  return {
    layout_bounds: { x, y, width, height },
    render_bounds: { x, y, width, height }
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
  // include_marks is intentionally omitted: the Rust core round-trips this
  // profile and does not yet carry the field, so asserting it here would test
  // the (separate) crates change rather than the editor operation path.
  embed_fonts: true
};

function assetPlaceholderNode(): Node {
  return {
    id: "node_hero_image",
    name: "Hero image",
    kind: { kind: "rect" },
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
      width: { kind: "fixed", value: 120 },
      height: { kind: "fixed", value: 67.5 }
    },
    children: [],
    fills: [],
    strokes: [],
    corner: { top_left: 0, top_right: 0, bottom_right: 0, bottom_left: 0 },
    opacity: 1,
    source_asset_id: null,
    asset_placement: null,
    clip: false,
    layout: null,
    computed: null,
    locked: false
  };
}

describe.skipIf(!wasmArtifactPresent)("engine operation application (wasm)", () => {
  let module: WasmModule;

  beforeAll(async () => {
    module = await loadWasmModuleFromDisk();
  });

  function engineWith(scene: Scene): WasmEngine {
    return new WasmEngine(module, scene);
  }

  it("replays explicit same-token sizes while raw inspector edits detach them", () => {
    const scene = cloneScene();
    const node = scene.nodes.node_contact_name;
    if (node.kind.kind !== "text") throw new Error("expected text node");
    node.kind.font_size_token = "type.size.7xl";
    node.kind.style_token = "type.display";
    const engine = engineWith(scene);
    const authoredKind = { ...node.kind, font_size: 80 };
    const authored = engine.applyOperations([{
      kind: "update_node",
      node_id: node.id,
      patch: nodePatch({ kind: set(authoredKind), explicit_text_tokens: { font_size: true } })
    }]);
    expect(authored.accepted).toBe(true);
    expect(engine.scene.nodes[node.id].kind).toMatchObject({
      font_size: 80,
      font_size_token: "type.size.7xl"
    });
    const raw = engine.applyOperations([updateTextNode(engine.scene.nodes[node.id], {
      font_size: 44
    })]);
    expect(raw.accepted).toBe(true);
    const rawKind = engine.scene.nodes[node.id].kind;
    if (rawKind.kind !== "text") throw new Error("expected text node");
    expect(rawKind.font_size).toBe(44);
    expect(rawKind.font_size_token).toBeUndefined();
    expect(rawKind.style_token).toBeUndefined();
  });

  it("applies editor-generated update node operations optimistically", () => {
    const scene = cloneScene();
    const engine = engineWith(scene);
    const node = scene.nodes.node_contact_name;
    const outcome = engine.applyOperations([
      updateNodeTransform(node, { ...node.transform, x: 42 })
    ]);

    expect(outcome.accepted).toBe(true);
    expect(engine.scene.nodes.node_contact_name.transform.x).toBe(42);
    // The input scene object is never mutated (immutable snapshots).
    expect(scene.nodes.node_contact_name.transform.x).toBe(24);
  });

  it("pins core lock semantics: raw operations apply, lock enforcement is edit/UI-layer", () => {
    // lumen-core enforces locks in the EDIT BUILDERS (Phase D unlock-as-
    // edit: EditErrorKind::LockedTarget) and the editor enforces them in
    // the UI guards; the raw operation layer applies patches verbatim on
    // the engine AND the server. The deleted TS mirror was stricter than
    // the server here — a latent optimistic/server divergence this suite
    // now pins shut.
    const scene = cloneScene();
    const engine = engineWith(scene);
    const locked = engine.applyOperations([
      updateNodeLocked(engine.scene.nodes.node_contact_name, true)
    ]);
    expect(locked.accepted).toBe(true);

    const rawGeometry = engine.applyOperations([
      updateNodeTransform(engine.scene.nodes.node_contact_name, {
        ...engine.scene.nodes.node_contact_name.transform,
        x: 80
      })
    ]);
    expect(rawGeometry.accepted).toBe(true);
    expect(engine.scene.nodes.node_contact_name.transform.x).toBe(80);

    // The structured-edit layer is where the lock holds.
    const structured = engine.applyStructuredEdit({
      kind: "modify",
      target: { kind: "node", id: "node_contact_name" },
      patch: { kind: "node", value: { text: { content: { kind: "set", value: "nope" } } } }
    });
    expect(structured.accepted).toBe(false);
    expect(structured.code).toBe("edit.locked_target");

    const unlocked = engine.applyOperations([
      updateNodeLocked(engine.scene.nodes.node_contact_name, false)
    ]);
    expect(unlocked.accepted).toBe(true);
    expect(engine.scene.nodes.node_contact_name.locked).toBe(false);
  });

  it("applies transform and size from a single resize operation", () => {
    const scene = cloneScene();
    const engine = engineWith(scene);
    const node = scene.nodes.node_contact_name;
    const outcome = engine.applyOperations([
      updateNodeTransformAndSize(
        node,
        { ...node.transform, x: 36, rotation: 8 },
        {
          width: { kind: "fixed", value: 120 },
          height: { kind: "fixed", value: 32 }
        }
      )
    ]);

    expect(outcome.accepted).toBe(true);
    expect(engine.scene.nodes.node_contact_name.transform.x).toBe(36);
    expect(engine.scene.nodes.node_contact_name.transform.rotation).toBe(8);
    expect(engine.scene.nodes.node_contact_name.size.width).toEqual({
      kind: "fixed",
      value: 120
    });
  });

  it("inserts nodes through the canonical operation shape", () => {
    const scene = cloneScene();
    const engine = engineWith(scene);
    const node: Node = {
      ...cloneScene().nodes.node_contact_name,
      id: "node_inserted_contact",
      name: "Inserted Contact",
      children: [],
      computed: null
    };

    const outcome = engine.applyOperations([
      insertNode({ kind: "page", id: "page_a4" }, 1, node)
    ]);
    expect(outcome.accepted).toBe(true);
    expect(engine.scene.pages.page_a4.children).toEqual([
      "node_contact_name",
      "node_inserted_contact"
    ]);
    expect(engine.scene.nodes.node_inserted_contact).toMatchObject({
      id: "node_inserted_contact",
      name: "Inserted Contact"
    });

    const rejected = engine.applyOperations([
      insertNode({ kind: "page", id: "missing_page" }, 0, {
        ...node,
        id: "node_missing_parent"
      })
    ]);
    expect(rejected.accepted).toBe(false);
    expect(rejected.message).toBeTruthy();
    expect(engine.scene.nodes.node_missing_parent).toBeUndefined();
  });

  it("accepts core-compatible parent refs that use id", () => {
    const scene = cloneScene();
    scene.pages.page_a4.children = [];
    const engine = engineWith(scene);
    const outcome = engine.applyOperations([
      {
        kind: "move_node",
        node_id: "node_contact_name",
        new_parent: { kind: "page", id: "page_a4" },
        index: 0
      }
    ]);

    expect(outcome.accepted).toBe(true);
    expect(engine.scene.pages.page_a4.children).toEqual(["node_contact_name"]);
  });

  it("rejects move operations that would corrupt the scene tree", () => {
    const scene = cloneScene();
    scene.nodes.node_frame = {
      ...scene.nodes.node_contact_name,
      id: "node_frame",
      name: "Frame",
      kind: { kind: "frame" },
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
    const engine = engineWith(scene);

    const leafParent = engine.applyOperations([
      moveNodeToParent("node_cta", { kind: "node", id: "node_contact_name" }, 0)
    ]);
    expect(leafParent.accepted).toBe(false);

    const descendantParent = engine.applyOperations([
      moveNodeToParent("node_frame", { kind: "node", id: "node_contact_name" }, 0)
    ]);
    expect(descendantParent.accepted).toBe(false);

    expect(engine.scene.pages.page_a4.children).toEqual(["node_frame", "node_cta"]);
    expect(engine.scene.nodes.node_frame.children).toEqual(["node_contact_name"]);
  });

  it("refreshes computed geometry after a local geometry edit", () => {
    // Editor coordinate-model fix: the engine relays out after every edit,
    // so `computed` is a coherent derived cache — never left null/stale for
    // the renderer. A transform edit refreshes the node's computed to its
    // new position (it does not invalidate-and-wait). The planted (320x48)
    // computed is arbitrary; relayout replaces it with the node's real
    // geometry (size 160x28 at the new x).
    const scene = cloneScene();
    scene.nodes.node_contact_name.computed = computedGeometry(24, 40, 320, 48);
    const engine = engineWith(scene);

    const outcome = engine.applyOperations([
      updateNodeTransform(engine.scene.nodes.node_contact_name, {
        ...engine.scene.nodes.node_contact_name.transform,
        x: 80
      })
    ]);

    expect(outcome.accepted).toBe(true);
    expect(engine.scene.nodes.node_contact_name.transform.x).toBe(80);
    const computed = engine.scene.nodes.node_contact_name.computed;
    expect(computed).not.toBeNull();
    expect(computed?.layout_bounds.x).toBe(80);
    expect(computed?.layout_bounds.width).toBe(160);
  });

  it("recomputes geometry, superseding an explicit computed patch", () => {
    // `computed` is engine-owned (relayout) in the editor: an explicit
    // computed patch does not stick — the relaid layout geometry wins. The
    // server, not an optimistic patch, owns canonical (Skia) geometry.
    const scene = cloneScene();
    const engine = engineWith(scene);
    const arbitrary = computedGeometry(12, 18, 240, 44);

    const outcome = engine.applyOperations([
      {
        kind: "update_node",
        node_id: "node_contact_name",
        patch: nodePatch({ computed: set(arbitrary) })
      }
    ]);

    expect(outcome.accepted).toBe(true);
    const computed = engine.scene.nodes.node_contact_name.computed;
    expect(computed).not.toEqual(arbitrary);
    expect(computed?.layout_bounds.x).toBe(24);
    expect(computed?.layout_bounds.width).toBe(160);
  });

  it("refreshes node computed after a page resize", () => {
    // The fix makes the editor's render geometry single-source and always
    // fresh: a page resize triggers a local relayout, so node computed is
    // recomputed immediately (not left stale until server preflight). The
    // server still owns canonical Skia geometry; this is the optimistic
    // local render cache, reconciled modulo computed.
    const scene = cloneScene();
    scene.nodes.node_contact_name.computed = computedGeometry(24, 40, 320, 48);
    const engine = engineWith(scene);
    const page = engine.scene.pages.page_a4;

    const outcome = engine.applyOperations([
      updatePageSize(page, {
        ...page.size,
        width: 1200,
        height: 628,
        unit: "px",
        preset: "custom"
      })
    ]);

    expect(outcome.accepted).toBe(true);
    expect(engine.scene.pages.page_a4.size).toMatchObject({
      width: 1200,
      height: 628,
      unit: "px",
      preset: "custom"
    });
    const computed = engine.scene.nodes.node_contact_name.computed;
    expect(computed).not.toEqual(computedGeometry(24, 40, 320, 48));
    expect(computed?.layout_bounds.x).toBe(24);
    expect(computed?.layout_bounds.width).toBe(160);
  });

  it("adds and removes custom pages through canonical page operations", () => {
    const scene = cloneScene();
    const engine = engineWith(scene);
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

    const added = engine.applyOperations([addPage(customPage)]);
    expect(added.accepted).toBe(true);
    expect(engine.scene.pages.page_square_ad.size).toMatchObject({
      width: 1080,
      height: 1080,
      unit: "px",
      preset: "custom"
    });

    const duplicate = engine.applyOperations([addPage(customPage)]);
    expect(duplicate.accepted).toBe(false);

    const child: Node = {
      ...cloneScene().nodes.node_contact_name,
      id: "node_custom_child",
      children: [],
      computed: null
    };
    const inserted = engine.applyOperations([
      insertNode({ kind: "page", id: "page_square_ad" }, 0, child)
    ]);
    expect(inserted.accepted).toBe(true);

    const removed = engine.applyOperations([removePage("page_square_ad")]);
    expect(removed.accepted).toBe(true);
    expect(engine.scene.pages.page_square_ad).toBeUndefined();
    expect(engine.scene.nodes.node_custom_child).toBeUndefined();
  });

  it("emits layout alignment updates as node layout patches", () => {
    const scene = cloneScene();
    const engine = engineWith(scene);
    const outcome = engine.applyOperations([
      updateAutoLayoutAlignment(engine.scene.nodes.node_contact_name, "center", "start")
    ]);

    expect(outcome.accepted).toBe(true);
    expect(engine.scene.nodes.node_contact_name.layout?.align_x).toBe("center");
    expect(engine.scene.nodes.node_contact_name.layout?.align_y).toBe("start");

    const cleared = engine.applyOperations([
      updateNodeLayout(engine.scene.nodes.node_contact_name, null)
    ]);
    expect(cleared.accepted).toBe(true);
    expect(engine.scene.nodes.node_contact_name.layout).toBeNull();
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
    scene.pages.page_a4.children.push("node_stack");
    const engine = engineWith(scene);

    const outcome = engine.applyOperations([
      updateAutoLayoutNode(engine.scene.nodes.node_stack, {
        direction: "row",
        wrap: true
      })
    ]);

    expect(outcome.accepted).toBe(true);
    expect(engine.scene.nodes.node_stack.kind).toMatchObject({
      kind: "auto_layout",
      direction: "row",
      wrap: true
    });
  });

  it("updates Phase B text metrics through the text node patch", () => {
    const scene = cloneScene();
    const engine = engineWith(scene);
    const outcome = engine.applyOperations([
      updateTextNode(engine.scene.nodes.node_contact_name, {
        line_height: 1.08,
        letter_spacing: -0.25,
        max_lines: 2,
        wrap: "wrap",
        direction: "auto"
      })
    ]);

    expect(outcome.accepted).toBe(true);
    expect(engine.scene.nodes.node_contact_name.kind).toMatchObject({
      kind: "text",
      line_height: 1.08,
      letter_spacing: -0.25,
      max_lines: 2,
      wrap: "wrap",
      direction: "auto"
    });
  });

  it("D4 span honesty holds on the whole-kind replace path: a content edit clears stale spans; undo restores them", () => {
    // A6b D9 verification, review-gate fixed: the inspector's content control
    // emits `updateTextNode(node, { content })` — a whole-kind
    // `Operation::UpdateNode` Set. The engine's update_node now applies span
    // honesty on that path too (operations.rs, beside clear_stale_tokens): a
    // content change carrying the OLD spans forward unchanged clears them
    // (stale byte offsets would silently mis-highlight the new string), and
    // the inverse frame restores content AND spans on undo.
    const scene = cloneScene();
    const span = { start: 4, end: 9, fill: { kind: "solid", color: { kind: "hex", value: "#ff0000" } } };
    (scene.nodes.node_contact_name.kind as { spans?: unknown }).spans = [span];
    const engine = engineWith(scene);
    // Precondition: the engine round-trips the authored spans.
    expect((engine.scene.nodes.node_contact_name.kind as { spans?: unknown }).spans).toEqual([span]);

    const before = engine.scene.nodes.node_contact_name;
    const originalContent = (before.kind as { content: string }).content;

    const edit = engine.applyOperations([
      updateTextNode(before, { content: "Totally different headline" })
    ]);
    expect(edit.accepted).toBe(true);
    const afterKind = engine.scene.nodes.node_contact_name.kind as { content: string; spans?: unknown };
    expect(afterKind.content).toBe("Totally different headline");
    // Stale spans cleared by the engine's whole-kind span honesty.
    expect(afterKind.spans ?? []).toEqual([]);

    // Undo restores the prior kind (content AND spans) via the inverse frame.
    const inverse = edit.inverseOperations;
    expect(inverse).toBeTruthy();
    const undo = engine.applyOperations(inverse!);
    expect(undo.accepted).toBe(true);
    const restored = engine.scene.nodes.node_contact_name.kind as { content: string; spans?: unknown };
    expect(restored.content).toBe(originalContent);
    expect(restored.spans).toEqual([span]);
  });

  it("upserts slots without reinterpreting slot semantics", () => {
    const scene = cloneScene();
    const engine = engineWith(scene);
    const slot = defaultTextSlot(
      "node_contact_name",
      "contact.title",
      "Contact title",
      "Chief Medical Officer"
    );
    const slotId = slotIdFromKey("contact.title");

    const outcome = engine.applyOperations([{ kind: "upsert_slot", slot }]);
    expect(outcome.accepted).toBe(true);
    expect(engine.scene.slots[slotId].key).toBe("contact.title");
    expect(engine.scene.slots[slotId].bound_nodes).toEqual(["node_contact_name"]);
  });

  it("applies asset registry and placement operations without redefining core semantics", () => {
    const scene = cloneScene();
    scene.nodes.node_hero_image = assetPlaceholderNode();
    scene.pages.page_a4.children.push("node_hero_image");
    const engine = engineWith(scene);

    const withAsset = engine.applyOperations([
      { kind: "upsert_asset", asset: generatedAsset() }
    ]);
    expect(withAsset.accepted).toBe(true);
    expect(engine.scene.assets.asset_generated_hero.kind).toBe("raster_image");

    const placed = engine.applyOperations([
      {
        kind: "place_asset_in_node",
        node_id: "node_hero_image",
        asset_id: "asset_generated_hero",
        placement: {
          fit: "cover",
          focal_point: { x: 0.5, y: 0.42 },
          preserve_transparency: false,
          alt_text: "Generated clinic hero"
        }
      }
    ]);
    expect(placed.accepted).toBe(true);
    expect(engine.scene.nodes.node_hero_image.kind).toEqual({
      kind: "image",
      asset_id: "asset_generated_hero",
      alt: "Generated clinic hero"
    });
    expect(engine.scene.nodes.node_hero_image.asset_placement?.fit).toBe("cover");

    const rejectedRemoval = engine.applyOperations([
      { kind: "remove_asset", asset_id: "asset_generated_hero" }
    ]);
    expect(rejectedRemoval.accepted).toBe(false);
    expect(engine.scene.assets.asset_generated_hero).toBeDefined();
  });

  it("applies export profile operations as canonical scene data", () => {
    const scene = cloneScene();
    const engine = engineWith(scene);
    const baseline = engine.scene.export_profiles.length;

    const withProfile = engine.applyOperations([upsertExportProfile(printPdfProfile)]);
    expect(withProfile.accepted).toBe(true);
    expect(engine.scene.export_profiles).toContainEqual(printPdfProfile);

    const updatedProfile = { ...printPdfProfile, include_bleed: false };
    const withUpdatedProfile = engine.applyOperations([upsertExportProfile(updatedProfile)]);
    expect(withUpdatedProfile.accepted).toBe(true);
    expect(engine.scene.export_profiles).toContainEqual(updatedProfile);
    expect(engine.scene.export_profiles).not.toContainEqual(printPdfProfile);

    const removedProfile = engine.applyOperations([
      removeExportProfile(printPdfProfile.name)
    ]);
    expect(removedProfile.accepted).toBe(true);
    expect(engine.scene.export_profiles.length).toBe(baseline);
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
    const engine = engineWith(scene);

    const removed = engine.applyOperations([removeNode("node_contact_name")]);
    expect(removed.accepted).toBe(true);
    expect(engine.scene.pages.page_a4.children).toEqual([]);
    expect(engine.scene.nodes.node_contact_name).toBeUndefined();
    expect(engine.scene.nodes.node_child).toBeUndefined();
    expect(engine.scene.slots.slot_contact_name.bound_nodes).toEqual([]);
  });

  it("hit-tests a point to the topmost node in page space (Wave 3 C3a)", () => {
    // node_contact_name relays out to computed (24,40,160,28) on page_a4.
    const engine = engineWith(cloneScene());

    const inside = engine.hitTest("page_a4", 30, 45);
    expect(inside.hit).toBe("node_contact_name");
    expect(inside.stack).toEqual(["node_contact_name"]);

    const outside = engine.hitTest("page_a4", 5, 5);
    expect(outside.hit).toBeNull();
    expect(outside.stack).toEqual([]);
  });
});
