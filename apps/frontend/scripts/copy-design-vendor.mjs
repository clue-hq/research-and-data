import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { copyFile, mkdir } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

// W1.4 (website-editor integration): vendor the Tailwind browser runtime the
// rendered web document loads from `/vendor/tailwind-browser.js`. The design
// editor's srcdoc iframe resolves that URL against the parent origin, so this
// app must serve the file itself; no upstream build step produces it. Wired
// into `prebuild`/`predev`; the output is gitignored (generated artifact).
const require = createRequire(import.meta.url);
const projectRoot = dirname(dirname(fileURLToPath(import.meta.url)));

// The package's main entry IS the browser bundle (dist/index.global.js).
const runtimeSource = require.resolve("@tailwindcss/browser");
const outputDir = join(projectRoot, "public", "vendor");
const outputPath = join(outputDir, "tailwind-browser.js");

await mkdir(outputDir, { recursive: true });
await copyFile(runtimeSource, outputPath);

// W4.8a: the SECOND vendored asset the injected bridge expects at the parent
// origin — `/vendor/web-rich-text-runtime.js`, the Lexical-backed in-iframe
// editing runtime (`lumen_api/web_bridge.py:424-444` injects only the lazy
// `<script>` loader and then reads `window.LumenRichTextRuntime`; the design
// API does not serve the bundle). The upstream dev editor produces it with a
// vite lib build; esbuild is the equivalent here and keeps this app off vite.
//
// `format: "iife"` because the frame loads it as a classic script; the global
// is assigned by the entry file itself, so no bundler `globalName` is needed.
// Minified: the bundle is ~third-party runtime weight, never read by hand.
// Lexical is bundled ONLY into this asset — no app module imports it, so
// nothing lands in the Next client bundle.
await build({
  bundle: true,
  entryPoints: [
    join(projectRoot, "src", "features", "design-editor", "iframe", "webRichTextRuntime.ts"),
  ],
  format: "iife",
  logLevel: "warning",
  minify: true,
  outfile: join(outputDir, "web-rich-text-runtime.js"),
  platform: "browser",
  target: "es2020",
});

// ── Scene editor vendor assets (ad editor, AD1.1) ──────────────────────────
// The scene (ad) editor renders through CanvasKit + the Rust engine compiled to
// wasm, both loaded from THIS origin — the upstream design editor serves them
// from its own `public/`, which this app does not have. Everything below lands
// under `public/vendor/` (gitignored) on every `predev`/`prebuild`.

// canvaskit.wasm: pinned 0.41.1 for render parity with the design subsystem.
const canvaskitWasm = require.resolve("canvaskit-wasm/bin/canvaskit.wasm");
await mkdir(join(outputDir, "canvaskit"), { recursive: true });
await copyFile(canvaskitWasm, join(outputDir, "canvaskit", "canvaskit.wasm"));

// Inter statics: TTF only — CanvasKit's FontMgr cannot read woff2.
const designRoot = join(projectRoot, "..", "..", "subsystems", "clue-design");
await mkdir(join(outputDir, "fonts"), { recursive: true });
for (const face of ["Inter-Regular", "Inter-SemiBold", "Inter-Bold", "Inter-ExtraBold"]) {
  await copyFile(
    join(designRoot, "fonts", `${face}.ttf`),
    join(outputDir, "fonts", `${face}.ttf`),
  );
}

// lumen_wasm: stamp-preflight (rebuilds on source drift when the Rust
// toolchain is present; exits 0 otherwise), then copy the artifacts.
// Missing artifacts are a WARNING, not a failure — the editor mounts
// read-only without wasm (runtime handshake owns the hard guarantee). This
// script gates every `dev`/`build`, so the whole wasm leg stays non-fatal:
// the preflight is designed to exit 0 even when it cannot rebuild, and a
// crash in it (missing script, node error) must not take the app down.
try {
  execFileSync("node", [join(designRoot, "scripts", "preflight_editor_wasm.mjs")], {
    cwd: designRoot,
    stdio: "inherit",
  });
} catch (error) {
  // Strict (Railway build, first deployment spec §9.5): a stale editor wasm must fail the
  // build, not warn — shipping it means an uneditable canvas for every user.
  if (process.env.WASM_PREFLIGHT_STRICT === "1") throw error;
  console.warn(
    `[copy-design-vendor] wasm preflight did not complete (${error instanceof Error ? error.message : error}) — continuing with whatever artifact exists.`,
  );
}
const wasmSrc = join(designRoot, "apps", "editor", "public", "wasm");
if (existsSync(join(wasmSrc, "lumen_wasm_bg.wasm"))) {
  await mkdir(join(outputDir, "wasm"), { recursive: true });
  for (const f of ["lumen_wasm.js", "lumen_wasm_bg.wasm"]) {
    await copyFile(join(wasmSrc, f), join(outputDir, "wasm", f));
  }
} else {
  console.warn(
    "[copy-design-vendor] lumen_wasm not built — scene editor will run read-only. Fix: npm --prefix ../../subsystems/clue-design/apps/editor run build:wasm",
  );
}
