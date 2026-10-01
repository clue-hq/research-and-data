#!/usr/bin/env node
// End-to-end version handshake evidence (Track E W5/W6): instantiate the
// built WASM module exactly as the browser would and compare its version
// payload against the helper binary's build_info. Exit 0 only when both
// report the identical { schema_version, engine_commit }.
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const wasmDir = path.join(root, "apps/editor/public/wasm");

const module = await import(pathToFileURL(path.join(wasmDir, "lumen_wasm.js")).href);
const bytes = readFileSync(path.join(wasmDir, "lumen_wasm_bg.wasm"));
try {
  module.initSync({ module: bytes });
} catch {
  module.initSync(bytes);
}
const moduleVersion = JSON.parse(module.engineVersion());

// HANDSHAKE_HELPER_CMD (deploy workflow, first deployment spec §9.5): ask the helper INSIDE the
// built image, so the check compares exactly the two artifacts that will be deployed. Unset =
// build and run it locally, as before.
const request = JSON.stringify({ action: "build_info" });
const helperCmd = process.env.HANDSHAKE_HELPER_CMD;
const helperOutput = helperCmd
  ? execFileSync("bash", ["-c", helperCmd], { input: request, encoding: "utf8" })
  : execFileSync(
      "cargo",
      ["run", "--quiet", "--manifest-path", path.join(root, "Cargo.toml"), "-p", "lumen-api-helper"],
      { input: request, encoding: "utf8" }
    );
const helperInfo = JSON.parse(helperOutput).build_info;

console.log("wasm module :", JSON.stringify(moduleVersion));
console.log("api helper  :", JSON.stringify(helperInfo));

const match =
  moduleVersion.schema_version === helperInfo.schema_version &&
  moduleVersion.engine_commit === helperInfo.engine_commit;

if (!match) {
  console.error("HANDSHAKE MISMATCH: editor would downgrade to server-only mode");
  process.exit(1);
}
console.log("HANDSHAKE OK: identical engine build on both sides");
