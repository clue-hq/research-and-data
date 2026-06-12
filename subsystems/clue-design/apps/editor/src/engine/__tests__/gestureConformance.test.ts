// @vitest-environment node
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import minimalSceneFixture from "../../../../../crates/lumen-core/fixtures/minimal_scene.json";
import type { Scene } from "../contracts";
import { WasmEngine } from "../wasmEngine";
import { runGestureScript, type GestureScriptResult } from "../../test/gestureScript";
import { loadWasmModuleFromDisk, wasmArtifactPresent } from "../../test/wasmModule";

/**
 * Track E conformance (W6 acceptance): the scripted gesture sequence —
 * canvas drag, resize, text edit, keyboard nudge, effects stack edit,
 * page rename — through the WASM engine must produce envelopes (wire
 * payloads + canonical operations) and a final scene IDENTICAL to the
 * pinned legacy-path output in
 * `fixtures/wasm-conformance/gesture-envelopes.json`, captured from the
 * legacy TS engine immediately before W4 retired it. Deep JSON equality,
 * no field skipping.
 *
 * The fixture is the legacy ground truth; it only changes via a
 * deliberate, reviewed regeneration.
 */

const FIXTURE_PATH = path.resolve(
  __dirname,
  "../../../../../fixtures/wasm-conformance/gesture-envelopes.json"
);

function cloneScene(): Scene {
  return JSON.parse(JSON.stringify(minimalSceneFixture)) as Scene;
}

function normalize(result: GestureScriptResult): unknown {
  return JSON.parse(JSON.stringify(result));
}

describe.skipIf(!wasmArtifactPresent)("gesture-script conformance (wasm vs pinned legacy)", () => {
  it("produces envelopes byte-identical to the pinned legacy-path fixture", async () => {
    expect(existsSync(FIXTURE_PATH), "pinned legacy fixture must exist").toBe(true);
    const module = await loadWasmModuleFromDisk();
    const engine = new WasmEngine(module, cloneScene());
    const result = normalize(runGestureScript(engine));
    const pinned = JSON.parse(readFileSync(FIXTURE_PATH, "utf8")) as unknown;
    expect(result).toEqual(pinned);
  });

  it("is deterministic across runs", async () => {
    const module = await loadWasmModuleFromDisk();
    const first = normalize(runGestureScript(new WasmEngine(module, cloneScene())));
    const second = normalize(runGestureScript(new WasmEngine(module, cloneScene())));
    expect(first).toEqual(second);
  });
});
