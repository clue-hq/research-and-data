// @vitest-environment node
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import minimalSceneFixture from "../../../../../crates/lumen-core/fixtures/minimal_scene.json";
import type { Scene } from "../contracts";
import { createLocalEnginePort } from "../editorEngine";
import { optimisticOperations } from "../structuredEdits";
import { WasmEngine } from "../wasmEngine";
import {
  runGestureScript,
  type GestureScriptResult,
  type GesturePort
} from "../../test/gestureScript";
import { loadWasmModuleFromDisk, wasmArtifactPresent } from "../../test/wasmModule";

/**
 * Track E conformance (W6 acceptance, fixture captured pre-W4): the same
 * scripted gesture sequence must produce IDENTICAL envelopes — wire
 * payloads, canonical operations, final scene — through the legacy TS
 * path and the WASM engine. Deep JSON equality, no field skipping.
 *
 * Regenerate the pinned fixture (deliberate, reviewed change only):
 *   GENERATE_GESTURE_FIXTURE=1 npx vitest run src/engine/__tests__/gestureConformance.test.ts
 */

const FIXTURE_PATH = path.resolve(
  __dirname,
  "../../../../../fixtures/wasm-conformance/gesture-envelopes.json"
);

function cloneScene(): Scene {
  return JSON.parse(JSON.stringify(minimalSceneFixture)) as Scene;
}

/** JSON-normalize so fixture comparisons are representation-stable. */
function normalize(result: GestureScriptResult): unknown {
  return JSON.parse(JSON.stringify(result));
}

function runLegacyScript(): unknown {
  const port: GesturePort = createLocalEnginePort(cloneScene());
  return normalize(
    runGestureScript(port, {
      structuredEditFallback: (scene, edit) => optimisticOperations(scene, edit)
    })
  );
}

function maybeGenerateFixture(result: unknown): void {
  if (process.env.GENERATE_GESTURE_FIXTURE === "1") {
    mkdirSync(path.dirname(FIXTURE_PATH), { recursive: true });
    writeFileSync(FIXTURE_PATH, `${JSON.stringify(result, null, 2)}\n`);
  }
}

describe("gesture-script conformance", () => {
  it("legacy path matches the pinned envelope fixture", () => {
    const result = runLegacyScript();
    maybeGenerateFixture(result);
    expect(existsSync(FIXTURE_PATH), "fixture missing — run with GENERATE_GESTURE_FIXTURE=1").toBe(
      true
    );
    const pinned = JSON.parse(readFileSync(FIXTURE_PATH, "utf8")) as unknown;
    expect(result).toEqual(pinned);
  });

  describe.skipIf(!wasmArtifactPresent)("wasm path", () => {
    it("produces envelopes byte-identical to the pinned legacy fixture", async () => {
      const module = await loadWasmModuleFromDisk();
      const engine = new WasmEngine(module, cloneScene());
      const result = normalize(runGestureScript(engine));
      const pinned = JSON.parse(readFileSync(FIXTURE_PATH, "utf8")) as unknown;
      expect(result).toEqual(pinned);
    });

    it("produces envelopes byte-identical to the legacy path run live", async () => {
      const module = await loadWasmModuleFromDisk();
      const legacy = runLegacyScript();
      const engine = new WasmEngine(module, cloneScene());
      const wasm = normalize(runGestureScript(engine));
      expect(wasm).toEqual(legacy);
    });
  });
});
