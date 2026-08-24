import { afterEach, describe, expect, it, vi } from "../../__tests__/vitest-shim";
import { minimalScene } from "./__fixtures__/minimalScene";
import {
  applyStructuredEdit,
  fetchHistory,
  groupEdit,
  mintGroupId,
  redoDocument,
  revertToCheckpoint,
  ungroupEdit,
  undoDocument
} from "../structuredEdits";

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

// Added at AD1 final review (not upstream): every document-API function in this
// module must route through an INJECTABLE transport. AD3/AD4 consumers reach the
// design API only through the BFF, and the same-origin re-mount lives inside
// designBffConfig()'s fetchImpl — a module-global `fetch` call would bypass it.
describe("structuredEdits transports are injectable", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const jsonResponse = (body: unknown): Response =>
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { "content-type": "application/json" }
    });

  /** The global is stubbed to a hard failure: any module-global call fails loudly. */
  function trapGlobalFetch() {
    const trap = vi.fn(async () => {
      throw new Error("structuredEdits must not call the module-global fetch");
    });
    vi.stubGlobal("fetch", trap);
    return trap;
  }

  it("routes every document-API call through the injected fetchImpl", async () => {
    const trap = trapGlobalFetch();
    const injected = vi.fn(async () => jsonResponse({ envelopes: [], envelope: null }));
    const transport = injected as unknown as typeof fetch;

    await applyStructuredEdit("http://api.test", "doc_1", ungroupEdit("g1"), {
      fetchImpl: transport
    });
    await fetchHistory("http://api.test", "doc_1", 50, transport);
    await undoDocument("http://api.test", "doc_1", transport);
    await redoDocument("http://api.test", "doc_1", transport);
    await revertToCheckpoint("http://api.test", "doc_1", "cp_1", transport);

    expect(injected.mock.calls).toHaveLength(5);
    expect(trap.mock.calls).toHaveLength(0);
    expect(injected.mock.calls.map((call) => String(call[0]))).toEqual([
      "http://api.test/documents/doc_1/edits",
      "http://api.test/documents/doc_1/history?limit=50",
      "http://api.test/documents/doc_1/undo",
      "http://api.test/documents/doc_1/redo",
      "http://api.test/documents/doc_1/revert?checkpoint=cp_1"
    ]);
  });
});
