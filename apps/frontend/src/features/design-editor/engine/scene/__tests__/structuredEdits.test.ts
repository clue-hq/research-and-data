import { describe, expect, it, vi } from "../../__tests__/vitest-shim";
import { minimalScene } from "./__fixtures__/minimalScene";
import { groupEdit, mintGroupId, ungroupEdit } from "../structuredEdits";

/**
 * Phase 4b arrange wire-shape smoke: these builders must emit exactly the
 * JSON the Rust `StructuredEditInstruction::Group`/`Ungroup` variants
 * deserialize (`#[serde(tag = "kind", rename_all = "snake_case")]` —
 * pinned by crates/lumen-core/tests/arrange_ops.rs's
 * `wire_format_kinds_are_pinned`). Z-order reuses the existing
 * `move_before`/`move_after` builders (already covered by the edit-parity
 * fixture), so it isn't retested here.
 */
describe("group/ungroup structured-edit wire shape", () => {
  it("builds the group wire format with a name", () => {
    expect(groupEdit(["a", "b"], "g1", "Group")).toEqual({
      kind: "group",
      node_ids: ["a", "b"],
      group_id: "g1",
      name: "Group"
    });
  });

  it("omits name when not provided", () => {
    expect(groupEdit(["a", "b"], "g1")).toEqual({
      kind: "group",
      node_ids: ["a", "b"],
      group_id: "g1"
    });
  });

  it("builds the ungroup wire format, defaulting allow_layout to false", () => {
    expect(ungroupEdit("g1")).toEqual({
      kind: "ungroup",
      node_id: "g1",
      allow_layout: false
    });
  });

  it("builds the ungroup wire format with allow_layout set", () => {
    expect(ungroupEdit("g1", true)).toEqual({
      kind: "ungroup",
      node_id: "g1",
      allow_layout: true
    });
  });

  describe("mintGroupId", () => {
    it("mints a grp-prefixed id not already present in the scene", () => {
      const id = mintGroupId(minimalScene);
      expect(id).toMatch(/^grp-[0-9a-f]{8}$/);
      expect(minimalScene.nodes[id]).toBeUndefined();
    });

    it("mints distinct ids across calls", () => {
      const first = mintGroupId(minimalScene);
      const second = mintGroupId(minimalScene);
      expect(first).not.toBe(second);
    });

    it("retries when the minted id already exists in the scene", () => {
      const uuids = ["aaaaaaaa-0000-0000-0000-000000000000", "bbbbbbbb-0000-0000-0000-000000000000"];
      const randomUUID = vi.spyOn(crypto, "randomUUID").mockImplementation(() => uuids.shift() as `${string}-${string}-${string}-${string}-${string}`);
      try {
        const scene = {
          ...minimalScene,
          nodes: { ...minimalScene.nodes, "grp-aaaaaaaa": minimalScene.nodes.node_contact_name }
        };
        expect(mintGroupId(scene)).toBe("grp-bbbbbbbb");
      } finally {
        randomUUID.mockRestore();
      }
    });
  });
});
