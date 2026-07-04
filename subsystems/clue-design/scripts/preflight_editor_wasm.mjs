#!/usr/bin/env node
// Dev preflight: keep the browser WASM engine matched to the current git HEAD
// so it can't silently drift out of sync with the API build. When they drift,
// the W5 handshake fails and the editor drops into server-only mode — a
// rendered-but-UNEDITABLE canvas, the worst failure for a human-editing tool.
//
// Why comparing to HEAD is sufficient: both the WASM crate and the API helper
// bake `git rev-parse --short=12 HEAD` as their engine_commit (crates/*/build.rs),
// and the handshake requires the two to be byte-identical. A freshly-started API
// helper is always at HEAD, so keeping the WASM at HEAD keeps the pair matched.
// (The full WASM-vs-helper check still lives in `scripts/dev-setup.sh prepare`.)
//
// Non-fatal by design: if the rebuild can't run (toolchain missing) we warn and
// let `next dev` start anyway — the in-app banner then explains the fix.
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const wasmDir = path.join(root, "apps/editor/public/wasm");
const jsEntry = path.join(wasmDir, "lumen_wasm.js");
const wasmBinary = path.join(wasmDir, "lumen_wasm_bg.wasm");

function headCommit() {
  try {
    return execFileSync("git", ["rev-parse", "--short=12", "HEAD"], {
      cwd: root,
      encoding: "utf8"
    }).trim();
  } catch {
    return null;
  }
}

// The engine_commit baked into the currently-built artifact, or null when it is
// missing or unreadable — both of which mean "rebuild".
async function builtCommit() {
  if (!existsSync(jsEntry) || !existsSync(wasmBinary)) {
    return null;
  }
  try {
    const module = await import(pathToFileURL(jsEntry).href);
    const bytes = readFileSync(wasmBinary);
    try {
      module.initSync({ module: bytes });
    } catch {
      module.initSync(bytes);
    }
    return JSON.parse(module.engineVersion()).engine_commit ?? null;
  } catch {
    return null;
  }
}

const head = headCommit();
if (!head) {
  console.warn("[wasm-preflight] not a git checkout — skipping engine staleness check");
  process.exit(0);
}

const built = await builtCommit();
if (built === head) {
  console.log(`[wasm-preflight] editor engine up to date (${head})`);
  process.exit(0);
}

console.log(
  `[wasm-preflight] editor engine ${built ?? "missing"} != HEAD ${head} — rebuilding to prevent server-only drift`
);
try {
  execFileSync("bash", [path.join(root, "scripts/build_wasm_core.sh")], {
    cwd: root,
    stdio: "inherit"
  });
  console.log(`[wasm-preflight] editor engine rebuilt at ${head}`);
} catch {
  console.warn(
    "\n[wasm-preflight] WARNING: could not rebuild the editor engine (is the wasm toolchain installed?).\n" +
      "                The editor will start in SERVER-ONLY mode — the canvas will not be editable.\n" +
      "                Fix: npm run build:wasm\n"
  );
}
process.exit(0);
