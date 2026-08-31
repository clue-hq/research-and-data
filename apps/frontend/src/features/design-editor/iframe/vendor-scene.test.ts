import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";

// AD1.1 guard: the scene (ad) editor renders through CanvasKit + the Rust
// engine wasm + Inter TTFs, all fetched from THIS origin (`/vendor/canvaskit`,
// `/vendor/wasm`, `/vendor/fonts/`). Nothing upstream serves them here, so a
// pipeline that silently stops emitting one of them is a runtime 404 on the
// canvas, not a build error. This test RUNS the pipeline (as `predev`/
// `prebuild` do) rather than inspecting stale artifacts, so it fails on a
// broken script, a moved source path, or a missing dependency.
//
// The wasm leg is deliberately conditional: `lumen_wasm_bg.wasm` only exists
// when the Rust toolchain could build it, and the pipeline treats its absence
// as a warning (the editor then mounts read-only). Asserting it
// unconditionally would fail on a toolchain-less machine for a state the
// product supports.

const projectRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "..");
const vendorDir = join(projectRoot, "public", "vendor");

// The engine bundle budget enforced by the design subsystem's
// `scripts/build_wasm_core.sh` (Track E). Re-asserted here because the copy
// crosses a subsystem seam: an over-budget artifact must not reach our origin.
const WASM_GZIP_BUDGET_BYTES = 3 * 1024 * 1024;

test("the prebuild vendor pipeline emits the scene editor runtime assets", () => {
  execFileSync(process.execPath, [join(projectRoot, "scripts", "copy-design-vendor.mjs")], {
    cwd: projectRoot,
    stdio: "pipe",
  });

  // CanvasKit: the renderer itself. >1MB is a sanity floor — the real binary is
  // ~7MB, so a truncated/placeholder copy fails here.
  const canvaskit = join(vendorDir, "canvaskit", "canvaskit.wasm");
  assert.ok(existsSync(canvaskit), `missing ${canvaskit}`);
  assert.ok(
    statSync(canvaskit).size > 1024 * 1024,
    `canvaskit.wasm looks truncated (${statSync(canvaskit).size} bytes)`,
  );

  // Inter statics: TTF only — CanvasKit's FontMgr cannot parse woff2, so a
  // missing face renders as fallback/blank text in the exported ad.
  for (const face of ["Inter-Regular", "Inter-SemiBold", "Inter-Bold", "Inter-ExtraBold"]) {
    const font = join(vendorDir, "fonts", `${face}.ttf`);
    assert.ok(existsSync(font), `missing ${font}`);
    assert.ok(statSync(font).size > 0, `${face}.ttf is empty`);
  }

  const engineWasm = join(vendorDir, "wasm", "lumen_wasm_bg.wasm");
  if (!existsSync(engineWasm)) {
    console.log(
      "[vendor-scene.test] lumen_wasm not built (no Rust/wasm toolchain?) — skipping engine assertions; the scene editor mounts read-only in this state.",
    );
    return;
  }

  // Its ES-module loader must ride along, or the binary is unloadable.
  assert.ok(existsSync(join(vendorDir, "wasm", "lumen_wasm.js")), "missing lumen_wasm.js");

  const gzipped = gzipSync(readFileSync(engineWasm), { level: 9 }).byteLength;
  assert.ok(
    gzipped < WASM_GZIP_BUDGET_BYTES,
    `lumen_wasm_bg.wasm is ${gzipped} bytes gzipped, over the ${WASM_GZIP_BUDGET_BYTES} budget`,
  );
});
