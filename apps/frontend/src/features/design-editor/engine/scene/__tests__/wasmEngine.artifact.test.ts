// @vitest-environment node
import { describe, expect, it, vi } from "../../__tests__/vitest-shim";

import { pressArmedAfterFreeze } from "../../../adapter/scene-gestures";
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

  /* --------------------------------------------------------------------
   * AD4.C-3 / ruling C-9 — the freeze the human's first grab fires.
   *
   * Asked of the REAL vendored engine rather than a fake, because every
   * property the host depends on is the engine's, not the port's: that the
   * edit is accepted at all, that it moves nothing, that it yields a plain
   * operation batch to persist, and that a second one is empty. If any of
   * these were false, freeze-on-grab would displace the ad on first touch.
   * ----------------------------------------------------------------- */

  /** The minimal scene with its text node re-parented under a Stack
   * auto-layout container — the class `freeze_layout` acts on. */
  function stackManagedScene(): Scene {
    const scene = cloneScene(baseScene);
    const child = scene.nodes.node_contact_name;
    scene.nodes.node_stack = {
      ...child,
      id: "node_stack",
      name: "Stack",
      kind: { kind: "auto_layout", direction: "column", wrap: false },
      layout: { gap: 8, grow: 0, padding: [12, 12, 12, 12], layout_mode: "stack" },
      children: ["node_contact_name"],
    } as (typeof scene.nodes)[string];
    scene.pages.page_a4.children = ["node_stack"];
    return scene;
  }

  function solvedBoxes(scene: Scene): Record<string, unknown> {
    return Object.fromEntries(
      Object.values(scene.nodes).map((node) => [
        node.id,
        node.computed ? { ...node.computed.layout_bounds } : null,
      ]),
    );
  }

  it("freeze_layout bakes a Stack container to free placement and moves nothing", async () => {
    const module = await loadWasmModuleFromDisk();
    const engine = new WasmEngine(module, stackManagedScene());
    const before = solvedBoxes(engine.scene);

    const outcome = engine.applyStructuredEdit({ kind: "freeze_layout" });

    expect(outcome.accepted).toBe(true);
    // A plain operation batch — what the host persists WITHOUT re-applying.
    expect(outcome.operations.length).toBeGreaterThan(0);
    // The container is no longer solver-owned, which is the whole point: the
    // very same press that fired this can now drag its child freely.
    expect(engine.scene.nodes.node_stack.layout?.layout_mode).toBe("free");
    // ZERO-MOTION. The gesture machine captures its start box at press-time
    // and never re-reads the scene, so a freeze that moved anything would make
    // the pre-freeze and post-freeze geometry disagree mid-drag.
    expect(solvedBoxes(engine.scene)).toEqual(before);
  });

  it("a second freeze_layout is an accepted no-op with nothing to persist", async () => {
    const module = await loadWasmModuleFromDisk();
    const engine = new WasmEngine(module, stackManagedScene());
    expect(engine.applyStructuredEdit({ kind: "freeze_layout" }).accepted).toBe(true);

    // Idempotent: this is what every press after the first one produces, and
    // it is why the host drops an empty batch instead of persisting it (the
    // design API's edits route answers an empty batch with a 422).
    const second = engine.applyStructuredEdit({ kind: "freeze_layout" });
    expect(second.accepted).toBe(true);
    expect(second.operations).toEqual([]);
  });

  /**
   * TWO Stack containers, one LOCKED — the case that breaks any guard reading
   * "was the freeze batch empty?" as "was THIS node freed?".
   *
   * `build_freeze_layout` iterates the whole document and skips only the
   * locked container, so the batch is non-empty (it carries the OTHER stack's
   * operations) while the locked container's child is still solver-owned. The
   * single-Stack fixture above cannot see the difference, which is exactly why
   * the first version of the host guard shipped wrong.
   */
  function twoStackScene(): Scene {
    const scene = cloneScene(baseScene);
    const template = scene.nodes.node_contact_name;
    const stack = (id: string, childId: string, locked: boolean) =>
      ({
        ...template,
        id,
        name: id,
        kind: { kind: "auto_layout", direction: "column", wrap: false },
        layout: { gap: 8, grow: 0, padding: [12, 12, 12, 12], layout_mode: "stack" },
        children: [childId],
        locked,
      }) as (typeof scene.nodes)[string];

    // `node_contact_name` stays — the document's one slot is bound to it, and
    // the engine refuses a scene whose slot points at a node that is gone. It
    // is the LOCKED container's child here.
    scene.nodes.node_free_child = { ...template, id: "node_free_child", children: [] };
    scene.nodes.node_stack_locked = stack("node_stack_locked", "node_contact_name", true);
    scene.nodes.node_stack_unlocked = stack("node_stack_unlocked", "node_free_child", false);
    scene.pages.page_a4.children = ["node_stack_locked", "node_stack_unlocked"];
    return scene;
  }

  it("freeze_layout frees the unlocked Stack while the locked one keeps its child — a NON-empty batch that did not free the pressed node", async () => {
    const module = await loadWasmModuleFromDisk();
    const engine = new WasmEngine(module, twoStackScene());

    const outcome = engine.applyStructuredEdit({ kind: "freeze_layout" });

    expect(outcome.accepted).toBe(true);
    // THE TRAP: non-empty, because the OTHER stack was freed.
    expect(outcome.operations.length).toBeGreaterThan(0);
    expect(outcome.scene.nodes.node_stack_unlocked.layout?.layout_mode).toBe("free");
    expect(outcome.scene.nodes.node_stack_locked.layout?.layout_mode ?? "stack").toBe("stack");

    // So the only sound question is asked of the node itself, on the POST-
    // freeze scene — not of the batch's size.
    expect(
      pressArmedAfterFreeze(outcome.scene, {
        kind: "node",
        nodeId: "node_contact_name",
        box: { x: 0, y: 0, width: 10, height: 10 },
        rotation: 0,
      }),
    ).toBe(false);
    expect(
      pressArmedAfterFreeze(outcome.scene, {
        kind: "node",
        nodeId: "node_free_child",
        box: { x: 0, y: 0, width: 10, height: 10 },
        rotation: 0,
      }),
    ).toBe(true);
  });

  it("freeze_layout leaves a LOCKED container alone", async () => {
    const module = await loadWasmModuleFromDisk();
    const scene = stackManagedScene();
    scene.nodes.node_stack.locked = true;
    const engine = new WasmEngine(module, scene);

    const outcome = engine.applyStructuredEdit({ kind: "freeze_layout" });

    expect(outcome.accepted).toBe(true);
    expect(outcome.operations).toEqual([]);
    // Still solver-owned. (The engine round-trips an unfrozen container with
    // the key absent, which reads as the "stack" default — the assertion that
    // carries meaning is that it is not "free".)
    expect(engine.scene.nodes.node_stack.layout?.layout_mode ?? "stack").toBe("stack");
  });
});
