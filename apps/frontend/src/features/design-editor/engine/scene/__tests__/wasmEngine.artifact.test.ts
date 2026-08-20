// @vitest-environment node
import { describe, expect, it, vi } from "../../__tests__/vitest-shim";

import parityFixture from "./__fixtures__/edit-parity-cases.json";
import minimalSceneFixture from "./__fixtures__/minimal_scene.json";
import type { Operation, Scene } from "../contracts";
import { updateNodeTransform, updateTextNode } from "../operations";
import type { StructuredEdit } from "../structuredEdits";
import { WasmEngine } from "../wasmEngine";
import { loadWasmModuleFromDisk, wasmArtifactPresent } from "./wasm-module-loader";

/**
 * The artifact-gated half of the upstream `wasmEngine.test.ts` (AD1.5 §6
 * deferred these 8 cases because the node loader and the vendored wasm-pack
 * artifact did not exist in the slice yet — AD1.6 ruling 9 brings them over).
 * The case bodies are verbatim; only the import paths moved. The pure
 * `applySceneDelta` cases stay in the sibling `wasmEngine.test.ts`.
 */

if (!wasmArtifactPresent) {
  console.log(
    "[wasmEngine.artifact] SKIPPED — no wasm artifact at public/vendor/wasm; " +
      "run `node scripts/copy-design-vendor.mjs` to vendor it.",
  );
}

const baseScene = minimalSceneFixture as unknown as Scene;

type ParityCase = {
  name: string;
  edit: StructuredEdit;
  expected_operations: Operation[];
};

const parityCases = (parityFixture as unknown as { cases: ParityCase[] }).cases;

function cloneScene(scene: Scene): Scene {
  return JSON.parse(JSON.stringify(scene)) as Scene;
}

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
