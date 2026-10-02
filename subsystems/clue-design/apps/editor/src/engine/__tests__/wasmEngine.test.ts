// @vitest-environment node
import { describe, expect, it, vi } from "vitest";

import parityFixture from "../../../../../fixtures/edit-parity/cases.json";
import minimalSceneFixture from "../../../../../crates/lumen-core/fixtures/minimal_scene.json";
import type { Operation, Scene } from "../contracts";
import { updateNodeTransform, updateTextNode } from "../operations";
import type { StructuredEdit } from "../structuredEdits";
import { applySceneDelta, WasmEngine, type SceneDelta, type WasmModule } from "../wasmEngine";
import { loadWasmModuleFromDisk, wasmArtifactPresent } from "../../test/wasmModule";

const baseScene = minimalSceneFixture as unknown as Scene;

type ParityCase = {
  name: string;
  edit: StructuredEdit;
  expected_operations: Operation[];
};

const parityCases = (parityFixture as { cases: ParityCase[] }).cases;

function cloneScene(scene: Scene): Scene {
  return JSON.parse(JSON.stringify(scene)) as Scene;
}

describe("applySceneDelta", () => {
  it("merges entity changes with structural sharing", () => {
    const scene = cloneScene(baseScene);
    const node = { ...scene.nodes.node_contact_name, name: "Renamed" };
    const delta: SceneDelta = { nodes: { node_contact_name: node } };

    const next = applySceneDelta(scene, delta);

    expect(next).not.toBe(scene);
    expect(next.nodes.node_contact_name).toBe(node);
    expect(next.pages).toBe(scene.pages);
    expect(next.slots).toBe(scene.slots);
    expect(scene.nodes.node_contact_name.name).not.toBe("Renamed");
  });

  it("removes entries for null delta values", () => {
    const scene = cloneScene(baseScene);
    const next = applySceneDelta(scene, { nodes: { node_contact_name: null } });
    expect(next.nodes.node_contact_name).toBeUndefined();
    expect(scene.nodes.node_contact_name).toBeDefined();
  });

  it("replaces export profiles wholesale", () => {
    const scene = cloneScene(baseScene);
    const profiles = [...scene.export_profiles];
    const next = applySceneDelta(scene, { export_profiles: profiles });
    expect(next.export_profiles).toBe(profiles);
  });
});

describe.skipIf(!wasmArtifactPresent)("WasmEngine (real artifact)", () => {
  it("reports the version handshake payload", async () => {
    const module = await loadWasmModuleFromDisk();
    const engine = new WasmEngine(module, cloneScene(baseScene));
    expect(engine.version.schema_version).toBe(1);
    expect(engine.version.engine_commit.length).toBeGreaterThan(0);
    expect(engine.version.text_measurement).toBe("heuristic");
  });

  it("produces the pinned parity operations for every structured edit case", async () => {
    const module = await loadWasmModuleFromDisk();
    for (const parityCase of parityCases) {
      const engine = new WasmEngine(module, cloneScene(baseScene));
      const outcome = engine.applyStructuredEdit(parityCase.edit);
      expect(outcome.accepted, parityCase.name).toBe(true);
      expect(outcome.operations, parityCase.name).toEqual(parityCase.expected_operations);
    }
  });

  it("keeps the delta-maintained snapshot identical to engine memory", async () => {
    const module = await loadWasmModuleFromDisk();
    for (const parityCase of parityCases) {
      const engine = new WasmEngine(module, cloneScene(baseScene));
      const outcome = engine.applyStructuredEdit(parityCase.edit);
      expect(outcome.accepted, parityCase.name).toBe(true);
      expect(outcome.scene, parityCase.name).toEqual(JSON.parse(engine.sceneJson()));
    }
  });

  it("rejects bad batches without mutating the scene", async () => {
    const module = await loadWasmModuleFromDisk();
    const engine = new WasmEngine(module, cloneScene(baseScene));
    const before = engine.scene;
    const outcome = engine.applyOperations([
      { kind: "remove_node", node_id: "node_does_not_exist" } as Operation
    ]);
    expect(outcome.accepted).toBe(false);
    expect(outcome.message).toBeTruthy();
    expect(engine.scene).toBe(before);
    expect(JSON.parse(engine.sceneJson())).toEqual(before);
  });

  it("never serializes the full scene during a 50-edit optimistic script", async () => {
    const module = await loadWasmModuleFromDisk();
    const engine = new WasmEngine(module, cloneScene(baseScene));
    const sceneJsonSpy = vi.spyOn(
      module.LumenEngine.prototype as unknown as { sceneJson: () => string },
      "sceneJson"
    );

    for (let index = 0; index < 50; index += 1) {
      const node = engine.scene.nodes.node_contact_name;
      const outcome = engine.applyOperations([
        index % 2 === 0
          ? updateTextNode(node, { content: `Keystroke ${index}` })
          : updateNodeTransform(node, { ...node.transform, x: index, y: index })
      ]);
      expect(outcome.accepted).toBe(true);
    }

    // Boundary discipline (Track E Decision 1): the optimistic path moves
    // deltas only; full-scene serialization stays at zero across the
    // 50-edit script and is used exactly once for the final equivalence
    // audit below.
    expect(sceneJsonSpy).toHaveBeenCalledTimes(0);
    expect(engine.scene).toEqual(JSON.parse(engine.sceneJson()));
    expect(sceneJsonSpy).toHaveBeenCalledTimes(1);
    sceneJsonSpy.mockRestore();
  });

  it("pins the TS slotIdFromKey mirror against the engine's derivation", async () => {
    const module = await loadWasmModuleFromDisk();
    const { slotIdFromKey } = await import("../operations");
    for (const key of [
      "account.name",
      "account_name",
      "contact.full_name",
      "campaign.cta",
      "research.key_insights",
      "x",
      "UPPER.case-key!"
    ]) {
      expect(slotIdFromKey(key), key).toBe(module.slotIdForKey(key));
    }
  });

  it("computes inverse operations that round-trip through reset-free undo", async () => {
    const module = await loadWasmModuleFromDisk();
    const engine = new WasmEngine(module, cloneScene(baseScene));
    const original = engine.scene;
    const node = engine.scene.nodes.node_contact_name;

    const outcome = engine.applyOperations([
      updateNodeTransform(node, { ...node.transform, x: 99, y: 1 })
    ]);
    expect(outcome.accepted).toBe(true);
    expect(outcome.inverseOperations).not.toBeNull();

    const undo = engine.applyOperations(outcome.inverseOperations ?? []);
    expect(undo.accepted).toBe(true);
    expect(undo.scene).toEqual(original);
  });

  it("round-trips an A6a decoration toggle through undo", async () => {
    const module = await loadWasmModuleFromDisk();
    const engine = new WasmEngine(module, cloneScene(baseScene));
    const original = engine.scene;
    const node = engine.scene.nodes.node_contact_name;

    // Toggle underline on through the single text-node op (no new op kind).
    const outcome = engine.applyOperations([updateTextNode(node, { underline: true })]);
    expect(outcome.accepted).toBe(true);
    expect(outcome.inverseOperations).not.toBeNull();
    const updated = engine.scene.nodes.node_contact_name.kind;
    expect(updated.kind).toBe("text");
    if (updated.kind === "text") {
      expect(updated.underline).toBe(true);
    }

    // The inverse batch restores the pre-toggle scene exactly (decoration off).
    const undo = engine.applyOperations(outcome.inverseOperations ?? []);
    expect(undo.accepted).toBe(true);
    expect(undo.scene).toEqual(original);
  });
});

it("keeps each mutation's presentation paired and rejects stale measurements", () => {
  const authored = cloneScene(baseScene);
  const presented = cloneScene(baseScene);
  presented.nodes.node_contact_name.name = "effective";
  let revision = 1;
  const metadata = () => ({ context_key: "ctx", input_revision: revision, status: "ready", diagnostics: [] });
  const module = { engineVersion: () => "{}", LumenEngine: class {
    sceneJson() { return JSON.stringify(authored); }
    presentationJson() { return JSON.stringify({ ...metadata(), scene: presented }); }
    setRenderContext() { return this.presentationJson(); }
    applyOperations() { revision++; return JSON.stringify({ ok:true, delta:{}, presentation_delta: { nodes: {
      node_contact_name: { ...presented.nodes.node_contact_name, name:"next" }
    } }, derivation:metadata() }); }
    setMeasurements() { throw new Error("stale measurement reached WASM"); }
  }} as unknown as WasmModule;
  const engine = new WasmEngine(module, authored);
  const before = engine.presentationScene;
  const stamp = engine.derivation.input_revision;
  const result = engine.applyOperations([]);
  expect(result.presentationScene?.nodes.node_contact_name.name).toBe("next");
  expect(before.nodes.node_contact_name.name).toBe("effective");
  expect(engine.scene.nodes.node_contact_name.name).not.toBe("next");
  expect(() => engine.setMeasurements([], stamp)).toThrow("Stale presentation");
});
