#!/usr/bin/env node
// Dev preflight: keep the browser WASM engine matched to the current engine
// SOURCES so it can't silently drift out of sync with the API build. When they
// drift, the W5 handshake fails and the editor drops into server-only mode — a
// rendered-but-UNEDITABLE canvas, the worst failure for a human-editing tool.
//
// Why comparing to a content hash (not git HEAD) is correct: both the WASM
// crate and the API helper bake `engine_commit` as a content hash of the shared
// engine sources (crates/build_support/engine_stamp.rs), and the handshake
// requires the two to be byte-identical. A freshly-started API helper always
// rebuilds at the current sources, so keeping the WASM stamp equal to the
// current source hash keeps the pair matched — and, unlike the old git-HEAD
// check, commits that don't touch engine sources no longer force a rebuild.
// (The full WASM-vs-helper check still lives in `scripts/dev-setup.sh prepare`.)
//
// Non-fatal by design in local dev: if the rebuild can't run (toolchain missing) we warn and
// let `next dev` start anyway — the in-app banner then explains the fix.
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

// Deploy/CI mode (first deployment spec §9.5): never rebuild, never warn-and-continue — a stale
// committed wasm FAILS, because shipping it means an uneditable canvas for every user. Set by the
// frontend's Railway build, the CI engine-handshake job and the deploy-images workflow.
const STRICT = process.env.WASM_PREFLIGHT_STRICT === "1";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const wasmDir = path.join(root, "apps/editor/public/wasm");
const jsEntry = path.join(wasmDir, "lumen_wasm.js");
const wasmBinary = path.join(wasmDir, "lumen_wasm_bg.wasm");

// The shared-engine closure hashed into the stamp — must mirror
// crates/build_support/engine_stamp.rs (lumen-core's src/**/*.rs + Cargo.toml,
// keyed by "../lumen-core/<relpath>" with forward slashes, sorted, then
// sha256 over (key\0 content\0) per file; first 12 hex chars).
const SHARED_ENGINE_CRATES = ["../lumen-core"];
// build.rs resolves the `../lumen-core` keys against CARGO_MANIFEST_DIR
// (crates/lumen-wasm). Mirror that base exactly so the derived stamp matches.
const MANIFEST_DIR = path.join(root, "crates/lumen-wasm");

function collectRsFiles(dir, srcParent, crateKey, out) {
  if (!existsSync(dir)) return;
  for (const name of readdirSync(dir).sort()) {
    const abs = path.join(dir, name);
    if (statSync(abs).isDirectory()) {
      collectRsFiles(abs, srcParent, crateKey, out);
    } else if (name.endsWith(".rs")) {
      const rel = path.relative(srcParent, abs).split(path.sep).join("/");
      out.push([`${crateKey}/${rel}`, abs]);
    }
  }
}

// The stamp the current engine sources would bake, computed the build.rs way.
function sourceStamp() {
  const files = [];
  for (const crateRel of SHARED_ENGINE_CRATES) {
    const crateRoot = path.join(MANIFEST_DIR, crateRel);
    const crateKey = crateRel.replace(/^\.\//, "");
    const cargoToml = path.join(crateRoot, "Cargo.toml");
    if (existsSync(cargoToml)) files.push([`${crateKey}/Cargo.toml`, cargoToml]);
    const srcRoot = path.join(crateRoot, "src");
    collectRsFiles(srcRoot, path.dirname(srcRoot), crateKey, files);
  }
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

let expected;
try {
  expected = sourceStamp();
} catch (error) {
  console.warn(
    `[wasm-preflight] could not hash engine sources (${error instanceof Error ? error.message : error}) — skipping staleness check`
  );
  process.exit(STRICT ? 1 : 0);
}

const built = await builtCommit();
if (built === expected) {
  console.log(`[wasm-preflight] editor engine up to date (${expected})`);
  process.exit(0);
}

if (STRICT) {
  console.error(
    `[wasm-preflight] STRICT: committed editor engine ${built ?? "missing"} != engine sources ${expected}.\n` +
      "  The browser wasm was not rebuilt after an engine change. Fix, then commit the result:\n" +
      "    bash subsystems/clue-design/scripts/build_wasm_core.sh\n" +
      "    node subsystems/clue-design/scripts/verify_handshake.mjs"
  );
  process.exit(1);
}

console.log(
  `[wasm-preflight] editor engine ${built ?? "missing"} != engine sources ${expected} — rebuilding to prevent server-only drift`
);
try {
  execFileSync("bash", [path.join(root, "scripts/build_wasm_core.sh")], {
    cwd: root,
    stdio: "inherit"
  });
  console.log(`[wasm-preflight] editor engine rebuilt at ${expected}`);
} catch {
  console.warn(
    "\n[wasm-preflight] WARNING: could not rebuild the editor engine (is the wasm toolchain installed?).\n" +
      "                The editor will start in SERVER-ONLY mode — the canvas will not be editable.\n" +
      "                Fix: npm run build:wasm\n"
  );
}
process.exit(0);
