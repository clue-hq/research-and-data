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
 *
 * Coordinate-model fix (2026-06-13): the engine now relays out every scene
 * it loads or mutates, so `finalScene` carries a fresh `computed` cache
 * where the retired TS path emitted `computed: null`. `computed` was never
 * part of the conformance contract — the guarantee this gate protects is
 * that the WASM engine's WIRE payloads, canonical operations, and authored
 * final scene are byte-identical to the legacy path. So the legacy
 * comparison strips `computed` (mirroring `without_computed` in the Rust
 * helper-parity test and `withoutComputed` in editQueue reconcile);
 * `computed` coherence is covered by the engine and wasmOperations tests,
 * and its run-to-run stability by the determinism case below (which keeps
 * `computed` in the comparison).
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

/**
 * Deep clone with every `computed` geometry field removed. `computed` is a
 * derived render cache the engine now keeps fresh on load/mutate; the
 * retired legacy path left it null. The conformance contract is the wire
 * payloads, canonical operations, and authored scene — not the cache — so
 * the legacy comparison strips it on both sides.
 */
function stripComputed<T>(value: T): T {
  if (Array.isArray(value)) {
    return value.map((entry) => stripComputed(entry)) as unknown as T;
  }
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [key, entry] of Object.entries(value as Record<string, unknown>)) {
      if (key === "computed") {
        continue;
      }
      out[key] = stripComputed(entry);
    }
    return out as T;
  }
  return value;
}

describe.skipIf(!wasmArtifactPresent)("gesture-script conformance (wasm vs pinned legacy)", () => {
  it("produces envelopes byte-identical to the pinned legacy-path fixture", async () => {
    expect(existsSync(FIXTURE_PATH), "pinned legacy fixture must exist").toBe(true);
    const module = await loadWasmModuleFromDisk();
    const engine = new WasmEngine(module, cloneScene());
    const result = normalize(runGestureScript(engine));
    const pinned = JSON.parse(readFileSync(FIXTURE_PATH, "utf8")) as unknown;
    // Compare the wire/authored contract only; `computed` is a derived cache
    // the legacy path left null (see file header). If anything authored
    // regressed, stripping `computed` would NOT hide it — this still fails.
    expect(stripComputed(result)).toEqual(stripComputed(pinned));
  });

  it("is deterministic across runs", async () => {
    const module = await loadWasmModuleFromDisk();
    const first = normalize(runGestureScript(new WasmEngine(module, cloneScene())));
    const second = normalize(runGestureScript(new WasmEngine(module, cloneScene())));
    expect(first).toEqual(second);
  });
});
