// @vitest-environment node
import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "../../__tests__/vitest-shim";

import minimalSceneFixture from "./__fixtures__/minimal_scene.json";
import type { Node, Operation, Scene } from "../contracts";
import { nodePatch, set } from "../operations";
import { loadWasmModuleFromDisk, wasmArtifactPresent } from "./wasm-module-loader";

/**
 * The AD1 exit-gate proof, in test form: the wasm engine the frontend ships
 * really runs, really accepts an operation built by the EXTRACTED
 * `operations.ts`, and really was built from the engine sources this repo
 * carries.
 *
 * The stamp half is the handshake's ground truth. `engine_commit` is a
 * content hash of `crates/lumen-core` (src/**\/*.rs + Cargo.toml), computed
 * identically by the wasm crate's `build.rs` and by the API helper — if the
 * vendored artifact's stamp drifts from the sources in this repo, the W5
 * handshake fails in the browser and the editor silently degrades to a
 * rendered-but-uneditable canvas. `sourceStamp()` below is a port of
 * `subsystems/clue-design/scripts/preflight_editor_wasm.mjs`'s function of the
 * same name (its lines 52-71), so the drift is caught here instead of there.
 */

const REPO_ROOT = path.resolve(__dirname, "../../../../../../../..");
const LUMEN_CORE = path.join(REPO_ROOT, "subsystems/clue-design/crates/lumen-core");

// build.rs keys the hashed files by their `../lumen-core/<relpath>` spec as
// resolved from `crates/lumen-wasm` — mirror that key exactly or the hash
// differs for identical bytes.
const CRATE_KEY = "../lumen-core";

if (!wasmArtifactPresent) {
  console.log(
    "[wasm-artifact] SKIPPED — no wasm artifact at public/vendor/wasm; " +
      "run `node scripts/copy-design-vendor.mjs` to vendor it.",
  );
}

function collectRsFiles(dir: string, srcParent: string, out: [string, string][]): void {
  if (!existsSync(dir)) return;
  for (const name of readdirSync(dir).sort()) {
    const abs = path.join(dir, name);
    if (statSync(abs).isDirectory()) {
      collectRsFiles(abs, srcParent, out);
    } else if (name.endsWith(".rs")) {
      const rel = path.relative(srcParent, abs).split(path.sep).join("/");
      out.push([`${CRATE_KEY}/${rel}`, abs]);
    }
  }
}

/** The stamp the current engine sources would bake, computed the build.rs way:
 * sorted by key, then sha256 over (key\0 content\0) per file, first 12 hex. */
function sourceStamp(): string {
  const files: [string, string][] = [];
  const cargoToml = path.join(LUMEN_CORE, "Cargo.toml");
  if (existsSync(cargoToml)) files.push([`${CRATE_KEY}/Cargo.toml`, cargoToml]);
  const srcRoot = path.join(LUMEN_CORE, "src");
  collectRsFiles(srcRoot, path.dirname(srcRoot), files);
  files.sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
  const hash = createHash("sha256");
  for (const [key, abs] of files) {
    hash.update(key);
    hash.update(Buffer.from([0]));
    hash.update(readFileSync(abs));
    hash.update(Buffer.from([0]));
  }
  return hash.digest("hex").slice(0, 12);
}

const minimalScene = minimalSceneFixture as unknown as Scene;

describe.skipIf(!wasmArtifactPresent)("vendored wasm artifact", () => {
  it("round-trips an operations.ts opacity patch through the real LumenEngine", async () => {
    const module = await loadWasmModuleFromDisk();
    const engine = new module.LumenEngine(JSON.stringify(minimalScene));

    const node: Node = minimalScene.nodes.node_contact_name;
    // The extracted builders, unmodified: one `update_node` carrying an
    // opacity patch and nothing else.
    const operation: Operation = {
      kind: "update_node",
      node_id: node.id,
      patch: nodePatch({ opacity: set(0.5) }),
    };

    // The engine's own wire result (`WasmEngine` is the typed wrapper over it).
    const outcome = JSON.parse(engine.applyOperations(JSON.stringify([operation]))) as {
      ok: boolean;
      applied_operations?: number;
      error?: { code: string; message: string };
    };
    expect(outcome.ok, outcome.error?.message ?? "no engine error").toBe(true);
    expect(outcome.applied_operations).toBe(1);

    // The engine actually applied it — not merely accepted the payload.
    const after = JSON.parse(engine.sceneJson()) as Scene;
    expect(after.nodes.node_contact_name.opacity).toBe(0.5);
  });

  it("was built from the lumen-core sources this repo carries (W5 stamp)", async () => {
    const module = await loadWasmModuleFromDisk();
    const version = JSON.parse(module.engineVersion()) as {
      schema_version: number;
      engine_commit: string;
    };
    expect(version.schema_version).toBe(1);
    expect(version.engine_commit).toBe(sourceStamp());
  });
});
