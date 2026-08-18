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
