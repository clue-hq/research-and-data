// @vitest-environment node
import { describe, expect, it } from "../../__tests__/vitest-shim";

import minimalSceneFixture from "./__fixtures__/minimal_scene.json";
import type { Scene } from "../contracts";
import { applySceneDelta, type SceneDelta } from "../wasmEngine";

/**
 * Ported at AD1.5 — the PURE cases only.
 *
 * The upstream file's second block (`describe.skipIf(!wasmArtifactPresent)`,
 * "WasmEngine (real artifact)", 8 cases) needed the built wasm artifact and the
 * `src/test/wasmModule.ts` disk loader, neither of which existed in the slice
 * at AD1.5. Both landed at AD1.6: those 8 cases now live verbatim in the
 * sibling `wasmEngine.artifact.test.ts`, gated on `wasmArtifactPresent`.
 */

const baseScene = minimalSceneFixture as unknown as Scene;

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
