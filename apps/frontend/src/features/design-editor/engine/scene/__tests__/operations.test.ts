import { describe, expect, it } from "../../__tests__/vitest-shim";
import { minimalScene } from "./__fixtures__/minimalScene";
import type { ComputedGeometry, Scene } from "../contracts";
import {
  nodePatch,
  set,
  slotIdFromKey,
  updateNodeLocked,
  updateNodeName,
  updateNodeTransform
} from "../operations";

/**
 * Wire-format builder tests. Operation APPLICATION coverage lives in
 * wasmOperations.test.ts against the real engine (W4 mirror retirement);
 * these tests pin the JSON shapes the builders emit.
 */

function cloneScene(): Scene {
  return JSON.parse(JSON.stringify(minimalScene)) as Scene;
}

describe("operation builders", () => {
  it("preserves supplied typography intent without adding it to raw edits", () => {
    const node = cloneScene().nodes.node_contact_name;
    const kind = set(node.kind);
    const explicit = JSON.parse(JSON.stringify(nodePatch({
      kind,
      explicit_text_tokens: { font_size: true, style: false }
    })));
    expect(explicit.explicit_text_tokens).toEqual({ font_size: true, style: false });
    const raw = JSON.parse(JSON.stringify(nodePatch({ kind })));
    expect(Object.hasOwn(raw, "explicit_text_tokens")).toBe(false);
  });

  it("builds canonical sparse node patches with explicit computed invalidation", () => {
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

    // Render-affecting patches carry `computed: clear` exactly like the
    // lumen-core edit builders (editing.rs node_patch_affects_render).
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
      computed: { kind: "clear" },
      locked: { kind: "unchanged" }
    });
  });

  it("leaves computed untouched for non-render patches", () => {
    const scene = cloneScene();
    const node = scene.nodes.node_contact_name;

    const renamed = updateNodeName(node, "Renamed");
    if (renamed.kind !== "update_node") {
      throw new Error("expected update_node operation");
    }
    expect(renamed.patch.computed).toEqual({ kind: "unchanged" });

    const locked = updateNodeLocked(node, true);
    if (locked.kind !== "update_node") {
      throw new Error("expected update_node operation");
    }
    expect(locked.patch.computed).toEqual({ kind: "unchanged" });
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

  it("derives deterministic collision-free editor slot ids", () => {
    const dotted = slotIdFromKey("account.name");
    const underscored = slotIdFromKey("account_name");

    expect(dotted).toMatch(/^slot_account_name_[0-9a-f]{16}$/);
    expect(underscored).toMatch(/^slot_account_name_[0-9a-f]{16}$/);
    expect(dotted).not.toBe(underscored);
    expect(slotIdFromKey("account.name")).toBe(dotted);
  });
});
