import { readFileSync } from "node:fs";
// @vitest-environment node
import { describe, expect, it, vi } from "../../__tests__/vitest-shim";

import { pressArmedAfterFreeze } from "../../../adapter/scene-gestures";
import { sceneChangeToOperation } from "../../../adapter/scene-apply";
import { hydrateSceneInspectorState } from "../../../adapter/scene-hydrate";
import type { KitTokenMaps } from "../tokenColors";
import parityFixture from "./__fixtures__/edit-parity-cases.json";
import minimalSceneFixture from "./__fixtures__/minimal_scene.json";
import type { Operation, Scene } from "../contracts";
import { nodePatch, set, updateNodeTransform, updateTextNode } from "../operations";
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
  it("canonical context resolves 72/token32 without changing authored values", async () => {
    const module = await loadWasmModuleFromDisk();
    const scene = cloneScene(baseScene);
    scene.slots = {}; scene.export_profiles = []; scene.meta.medium = "digital";
    const child = scene.nodes.node_contact_name;
    scene.nodes.frame = { ...child, id:"frame", kind:{ kind:"auto_layout", direction:"column", wrap:false },
      transform:{ ...child.transform, x:0, y:0 },
      size:{ width:{kind:"fixed",value:500}, height:{kind:"fixed",value:500} },
      children:[child.id], layout:{ gap:72, gap_token:"space.md", padding:[72,72,72,72], padding_token:"space.md", grow:0 } };
    scene.pages.page_a4.children = ["frame"];
    const kit = JSON.parse(readFileSync(new URL("../../../../../../../../subsystems/clue-design/crates/lumen-core/fixtures/brand_kits/platform_default.json", import.meta.url), "utf8"));
    kit.tokens.spacing["space.md"].value.default.value = 32;
    const engine = new WasmEngine(module, scene);
    expect(engine.scene.nodes.node_contact_name.computed?.layout_bounds.x).toBe(72);
    engine.setRenderContext({ context_key:"fixture", document_id:scene.meta.id, document_version:1,
      scene_brand_ref:null, scene_medium:"digital", source:"test", brand_kit:kit, mode:null, diagnostics:[] });
    expect(engine.derivation.status).toBe("ready");
    expect(engine.scene.nodes.frame.layout?.padding).toEqual([72,72,72,72]);
    expect(engine.presentationScene.nodes.frame.layout?.padding).toEqual([32,32,32,32]);
    expect(engine.presentationScene.nodes.node_contact_name.computed?.layout_bounds.x).toBe(32);
  });

  for (const [property, value, expectedFamily, expectedSize, expectedWeight] of [
    ["fontSize", "72", "Season Mix", 72, 500],
    ["fontSize", "16", "Season Mix", 16, 500],
    ["fontFamily", "Mona Sans", "Mona Sans", 67.5, 500],
    ["fontWeight", "700 Bold", "Season Mix", 67.5, 700],
  ] as const) {
    it(`inspector ${property}=${value} preserves other effective typography through replay and undo`, async () => {
      const module = await loadWasmModuleFromDisk();
      const scene = cloneScene(baseScene);
      const node = scene.nodes.node_contact_name;
      if (node.kind.kind !== "text") throw new Error("expected text");
      node.kind = { ...node.kind, font_family: "Inter", font_size: 16, font_weight: 400,
        line_height: 1.04, letter_spacing: 0, style_token: "type.headline",
        font_size_token: "type.size.6xl", line_height_token: "type.leading",
        letter_spacing_token: "type.tracking" };
      const maps: KitTokenMaps = { colors: {}, typography: {
        "type.headline": { fontFamily: "Season Mix", fontSize: 80, fontWeight: 500,
          lineHeight: 1.12, letterSpacing: -0.6 },
      }, numbers: { "type.size.6xl": 67.5, "type.leading": 1.4, "type.tracking": 2 } };
      const before = JSON.stringify(scene);
      const operation = sceneChangeToOperation({ property, value, selectionId: node.id }, node, scene, null, maps);
      expect(operation).not.toBeNull();
      expect(JSON.stringify(scene)).toBe(before);
      const engine = new WasmEngine(module, scene);
      const original = engine.scene.nodes[node.id].kind;
      const result = engine.applyOperations([operation!]);
      expect(result.accepted).toBe(true);
      const edited = engine.scene.nodes[node.id];
      expect(edited.kind).toMatchObject({ font_family: expectedFamily, font_size: expectedSize,
        font_weight: expectedWeight, line_height: 1.12, letter_spacing: -0.6 });
      if (edited.kind.kind !== "text") throw new Error("expected text");
      expect(edited.kind.style_token ?? null).toBeNull();
      expect(edited.kind.line_height_token ?? null).toBeNull();
      expect(edited.kind.letter_spacing_token ?? null).toBeNull();
      expect(edited.kind.font_size_token ?? null).toBe(property === "fontSize" ? null : "type.size.6xl");
      expect(hydrateSceneInspectorState(edited, engine.scene, maps).fontSize).toBe(String(expectedSize));
      const replay = new WasmEngine(module, JSON.parse(before));
      expect(replay.applyOperations(JSON.parse(JSON.stringify([operation]))).accepted).toBe(true);
      expect(replay.scene.nodes[node.id].kind).toEqual(edited.kind);
      if (!result.inverseOperations) throw new Error("expected an undo operation");
      expect(engine.applyOperations(result.inverseOperations).accepted).toBe(true);
      expect(engine.scene.nodes[node.id].kind).toEqual(original);
      expect(sceneChangeToOperation({ property: "fontSize", value: "67.5", selectionId: node.id }, node, scene, null, maps)).toBeNull();
    });
  }

  it("keeps untouched leading and tracking tokens when they preserve the visible role values", async () => {
    const module = await loadWasmModuleFromDisk();
    const scene = cloneScene(baseScene);
    const node = scene.nodes.node_contact_name;
    if (node.kind.kind !== "text") throw new Error("expected text");
    node.kind = { ...node.kind, font_family: "Inter", font_size: 16, font_weight: 400,
      style_token: "type.headline", line_height_token: "type.leading",
      letter_spacing_token: "type.tracking" };
    const maps: KitTokenMaps = { colors: {}, typography: {
      "type.headline": { fontFamily: "Season Mix", fontSize: 80, fontWeight: 500,
        lineHeight: 1.12, letterSpacing: -0.6 },
    }, numbers: { "type.leading": 1.12, "type.tracking": -0.6 } };
    const operation = sceneChangeToOperation({ property: "fontSize", value: "72", selectionId: node.id }, node, scene, null, maps);
    expect(operation).not.toBeNull();
    const engine = new WasmEngine(module, scene);
    expect(engine.applyOperations(JSON.parse(JSON.stringify([operation]))).accepted).toBe(true);
    expect(engine.scene.nodes[node.id].kind).toMatchObject({ font_family: "Season Mix",
      font_size: 72, font_weight: 500, line_height: 1.12, letter_spacing: -0.6,
      line_height_token: "type.leading", letter_spacing_token: "type.tracking" });
  });

  it("preserves explicit typography intent through replay and undo before raw edits detach", async () => {
    const module = await loadWasmModuleFromDisk();
    const scene = cloneScene(baseScene);
    const node = scene.nodes.node_contact_name;
    if (node.kind.kind !== "text") throw new Error("expected text node");
    node.kind.font_size_token = "type.size.7xl";
    node.kind.style_token = "type.display";
    const engine = new WasmEngine(module, scene);
    const original = engine.scene.nodes[node.id].kind;
    const authored = engine.applyOperations([{
      kind: "update_node",
      node_id: node.id,
      patch: nodePatch({
        kind: set({ ...node.kind, font_size: 80 }),
        explicit_text_tokens: { font_size: true, style: true }
      })
    }]);
    expect(authored.accepted).toBe(true);
    expect(engine.scene.nodes[node.id].kind).toMatchObject({
      font_size: 80, font_size_token: "type.size.7xl", style_token: "type.display"
    });
    const undo = engine.applyOperations(JSON.parse(JSON.stringify(authored.inverseOperations)));
    expect(undo.accepted).toBe(true);
    expect(engine.scene.nodes[node.id].kind).toEqual(original);
    const redo = engine.applyOperations(JSON.parse(JSON.stringify(undo.inverseOperations)));
    expect(redo.accepted).toBe(true);
    expect(engine.scene.nodes[node.id].kind).toMatchObject({
      font_size: 80, font_size_token: "type.size.7xl", style_token: "type.display"
    });
    const raw = engine.applyOperations([updateTextNode(engine.scene.nodes[node.id], { font_size: 44 })]);
    expect(raw.accepted).toBe(true);
    const rawKind = engine.scene.nodes[node.id].kind;
    if (rawKind.kind !== "text") throw new Error("expected text node");
    expect(rawKind.font_size).toBe(44);
    expect(rawKind.font_size_token).toBeUndefined();
    expect(rawKind.style_token).toBeUndefined();
  });

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

  /** The Story-ad shape that contracted live (2026-08-22): a PADDED Stack
   * container whose own height is HUG, under a plain page parent (no frozen
   * parent bakes it). Pre-fix the engine left the container's Hug alone and
   * Free-mode hug dropped the padding — the card visibly shrank by its
   * bottom inset on the human's first grab. The engine now bakes the
   * container's OWN Hug dims to Fixed at the solved extent, so this asserts
   * the full zero-motion contract through the real vendored build. */
  function paddedHugScene(): Scene {
    const scene = stackManagedScene();
    const stack = scene.nodes.node_stack;
    stack.size = { width: { kind: "fixed", value: 400 }, height: { kind: "hug" } };
    stack.layout = { gap: 8, grow: 0, padding: [40, 44, 40, 44], layout_mode: "stack" };
    return scene;
  }

  it("freeze_layout bakes a padded hug container's own dims — the padded box survives", async () => {
    const module = await loadWasmModuleFromDisk();
    const engine = new WasmEngine(module, paddedHugScene());
    const before = solvedBoxes(engine.scene);
    const containerBefore = engine.scene.nodes.node_stack.computed?.layout_bounds;
    expect(containerBefore).toBeDefined();

    const outcome = engine.applyStructuredEdit({ kind: "freeze_layout" });

    expect(outcome.accepted).toBe(true);
    expect(engine.scene.nodes.node_stack.layout?.layout_mode).toBe("free");
    // The container's own Hug height baked to Fixed at the solved extent…
    expect(engine.scene.nodes.node_stack.size.height).toEqual({
      kind: "fixed",
      value: containerBefore?.height,
    });
    // …its authored Fixed width kept its value…
    expect(engine.scene.nodes.node_stack.size.width).toEqual({ kind: "fixed", value: 400 });
    // …and NOTHING moved: the padded box is byte-identical post-freeze.
    expect(solvedBoxes(engine.scene)).toEqual(before);

    // The inverse restores Hug (the undo that un-freezes restores the solve).
    const undo = engine.applyOperations(outcome.inverseOperations ?? []);
    expect(undo.accepted).toBe(true);
    expect(undo.scene.nodes.node_stack.size.height).toEqual({ kind: "hug" });
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

  /* --------------------------------------------------------------------
   * The three REAL ads, at the wasm seam (Task 5).
   *
   * `crates/lumen-core/tests/freeze_real_ads.rs` asks the Rust engine the
   * same question of the same three fixtures. This asks it of the artifact
   * the BROWSER actually loads, which is a different claim: the vendored
   * wasm is a build, and a build can lag the crate. These are the LinkedIn
   * ads the human froze on the live walk 2026-09-20, recovered pre-freeze
   * (`computed: null` on every node, no `layout_mode` keys) — the shape the
   * agent authors, not a hand-written stack.
   * ----------------------------------------------------------------- */

  function loadFreezeFixture(name: string): Scene {
    return JSON.parse(
      readFileSync(new URL(`./__fixtures__/freeze/${name}.json`, import.meta.url), "utf8"),
    ) as Scene;
  }

  /**
   * Every box, to 1e-6 — except the HEIGHT of the named text nodes, to 1.0px.
   *
   * The slack is the engine's one documented residual (Task 1): the Stack
   * solve reports taffy's whole-pixel-ROUNDED geometry while Free natural-
   * sizes unrounded, so a TEXT node that keeps its `hug` height through the
   * freeze (the one dimension deliberately left un-baked) re-measures up to
   * 0.71px different. Everything else is a baked Fixed extent or a baked
   * transform, where any drift at all is a regression — which is why the
   * grant is a named list and not a global tolerance.
   *
   * Violations are COLLECTED, never short-circuited: a failure has to name
   * every node that moved, the way the Rust twin does.
   */
  function expectZeroMotion(
    before: Record<string, unknown>,
    after: Record<string, unknown>,
    textHeightSlack: string[],
  ): void {
    expect(Object.keys(after).sort()).toEqual(Object.keys(before).sort());
    const violations: string[] = [];
    for (const [id, wasBox] of Object.entries(before)) {
      const nowBox = after[id];
      if (wasBox === null || nowBox === null) {
        // A node the solve does not place has no box to move; it must simply
        // be un-placed on BOTH sides.
        if (wasBox !== nowBox) {
          violations.push(`${id}: placed on one side only`);
        }
        continue;
      }
      const was = wasBox as { x: number; y: number; width: number; height: number };
      const now = nowBox as typeof was;
      const heightTolerance = textHeightSlack.includes(id) ? 1.0 : 1e-6;
      for (const [axis, from, to, tolerance] of [
        ["x", was.x, now.x, 1e-6],
        ["y", was.y, now.y, 1e-6],
        ["width", was.width, now.width, 1e-6],
        ["height", was.height, now.height, heightTolerance],
      ] as const) {
        const delta = Math.abs(to - from);
        if (delta > tolerance) {
          violations.push(`${id}.${axis}: ${from} -> ${to} (delta ${delta}, tolerance ${tolerance})`);
        }
      }
    }
    expect(violations).toEqual([]);
  }

  /** The hug-height text nodes of each ad — the same lists the Rust twin
   * grants, node for node. */
  const REAL_AD_FREEZE_CASES: Array<{ name: string; textHeightSlack: string[] }> = [
    {
      name: "capital_digestive_care_ad",
      textHeightSlack: [
        "eyebrow",
        "headline",
        "kicker",
        "pair_x",
        "prod_dac",
        "prod_intake",
        "prod_magicdocs",
        "support",
      ],
    },
    {
      name: "austin_gastroenterology_ad",
      textHeightSlack: ["cta", "headline", "sep", "support"],
    },
    {
      name: "mngi_digestive_health_ad",
      textHeightSlack: ["cta", "headline", "logo_sep", "p1", "p2", "p3", "support"],
    },
  ];

  for (const { name, textHeightSlack } of REAL_AD_FREEZE_CASES) {
    it(`freeze_layout moves nothing on the real ad ${name}`, async () => {
      const module = await loadWasmModuleFromDisk();
      // The engine relays out on load, so `engine.scene` is the SOLVED ad —
      // the geometry the gesture machine captures at press time.
      const engine = new WasmEngine(module, loadFreezeFixture(name));
      const before = solvedBoxes(engine.scene);

      const outcome = engine.applyStructuredEdit({ kind: "freeze_layout" });

      expect(outcome.accepted).toBe(true);
      // Non-empty, or the fixture had no managed container left and the case
      // would be proving nothing.
      expect(outcome.operations.length).toBeGreaterThan(0);
      expectZeroMotion(before, solvedBoxes(outcome.scene), textHeightSlack);

      // The slack can never quietly cover a baked extent that drifted: each
      // granted node really is a text node that kept its hug height.
      for (const id of textHeightSlack) {
        const node = outcome.scene.nodes[id];
        expect(node?.kind.kind, `${name}/${id} kind`).toBe("text");
        expect(node?.size.height, `${name}/${id} height`).toEqual({ kind: "hug" });
      }
    });
  }
});
