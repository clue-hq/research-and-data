import { copyFile, mkdir } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

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
