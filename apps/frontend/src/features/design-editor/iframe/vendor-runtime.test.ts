import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

// W4.8a guard: the vendor pipeline really produces the asset the injected
// bridge fetches. `lumen_api/web_bridge.py:424-444` appends
// `<script src="/vendor/web-rich-text-runtime.js?v=structured-blocks-v2">` to
// the sandboxed srcdoc and then reads `window.LumenRichTextRuntime`; the
// design API serves only that loader, so a missing bundle here is a silent
// 404 and every double-click edit dies as `edit-error` at runtime. This test
// RUNS the pipeline (not just checks a stale artifact), so it fails on a
// broken build script, a moved entry point, or a Lexical resolution error.

const projectRoot = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
  "..",
  "..",
);
const bundlePath = join(projectRoot, "public", "vendor", "web-rich-text-runtime.js");

test("the prebuild vendor pipeline emits the rich-text runtime bundle", () => {
  execFileSync(process.execPath, [join(projectRoot, "scripts", "copy-design-vendor.mjs")], {
    cwd: projectRoot,
    stdio: "pipe",
  });
  const bundle = readFileSync(bundlePath, "utf8");

  // The exact global the bridge loader reads back after the script settles.
  assert.match(bundle, /window\.LumenRichTextRuntime\s*=/);
  // A classic-script IIFE: the frame loads it with a plain <script> tag, so an
  // ESM bundle (bare `import`/`export`) would never execute there.
  assert.ok(bundle.startsWith('"use strict";(()=>{'), "expected a minified IIFE");
  assert.doesNotMatch(bundle, /^\s*import[\s{]/m);
  assert.doesNotMatch(bundle, /^\s*export[\s{]/m);
  // Lexical must be bundled IN (self-contained), never left as a bare
  // specifier the browser cannot resolve.
  assert.doesNotMatch(bundle, /from\s*["']lexical["']/);
});
