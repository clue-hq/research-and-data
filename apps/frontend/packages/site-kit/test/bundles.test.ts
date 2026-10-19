// The CLIs the design API and the site harness run ship as single files: they must work with
// plain node from a directory that has no node_modules at all.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { garner, site as readSite } from "./fixtures/garner";

const root = fileURLToPath(new URL("..", import.meta.url));
const site = readSite("garner-syracuse");
const brand = garner();

test("the build writes the validator and the catalog as single files that run with plain node", () => {
  execFileSync(process.execPath, ["bin/build-bundles.mjs"], { cwd: root });
  const validator = path.join(root, "dist", "validate-site.mjs");
  const catalog = path.join(root, "dist", "build-catalog.mjs");
  assert.ok(fs.existsSync(validator) && fs.existsSync(catalog));
  const browser = path.join(root, "dist", "render-browser.js");
  assert.ok(fs.existsSync(browser), "the render bundle is built");
  const text = fs.readFileSync(browser, "utf-8");
  assert.ok(text.length > 100_000 && !/^\s*import\s/m.test(text.slice(0, 2000)), "one classic script, nothing to resolve");
  assert.ok(text.includes("__clueRender") && text.includes("clue-render-input"));
  const away = fs.mkdtempSync(path.join(os.tmpdir(), "site-kit-bundle-"));
  try {
    const checked = JSON.parse(
      execFileSync(process.execPath, [validator], { cwd: away, input: JSON.stringify({ files: { pages: site.pages, shell: site.shell }, brand }) }).toString(),
    );
    assert.deepEqual(checked, { valid: true, errors: [] });
    const built = JSON.parse(execFileSync(process.execPath, [catalog], { cwd: away, input: JSON.stringify({ brand, seller: "Garner Health" }) }).toString());
    assert.ok(built.files["brand/brand.md"].startsWith("# Brand: Garner Health"));
    assert.ok(Object.keys(built.files).includes("catalog/index.md"));
  } finally {
    fs.rmSync(away, { recursive: true, force: true });
  }
});

test("the build writes the site runtime as one ES module and a shim per host library", () => {
  execFileSync(process.execPath, ["bin/build-bundles.mjs"], { cwd: root });
  const runtime = fs.readFileSync(path.join(root, "dist", "site-runtime.js"), "utf-8");
  assert.ok(runtime.includes("clue-page-data") && runtime.includes("__clueHydrated") && runtime.includes("__clueSectionHost"));
  for (const file of ["react.js", "react-jsx-runtime.js", "zod.js"]) {
    const shim = fs.readFileSync(path.join(root, "dist", "site-runtime-shims", file), "utf-8");
    assert.ok(shim.startsWith("const m = globalThis.__clueSectionHost"), file);
  }
  assert.ok(fs.readFileSync(path.join(root, "dist", "site-runtime-shims", "react.js"), "utf-8").includes(" cache"));
});

test("the site runtime carries only what a published page runs: no editor code, no HTML parser", () => {
  execFileSync(process.execPath, ["bin/build-bundles.mjs"], { cwd: root });
  // The build's own report of the packages inside dist/site-runtime.js, with their bytes.
  const report = JSON.parse(fs.readFileSync(path.join(root, "dist", "site-runtime.packages.json"), "utf-8")) as {
    bytes: number;
    packages: Record<string, number>;
  };
  // Puck's editor (rich text, drag and drop, list virtualising) and the clone filler's HTML parser:
  // a published page draws with Puck's render-only Render, and its cloned sections keep the
  // server's markup.
  const editorOnly = ["@tiptap/core", "prosemirror-view", "@dnd-kit/dom", "@tanstack/virtual-core", "object-hash", "node-html-parser", "he", "css-select"];
  assert.deepEqual(editorOnly.filter((name) => name in report.packages), []);
  const runtime = fs.statSync(path.join(root, "dist", "site-runtime.js")).size;
  assert.equal(report.bytes, runtime);
  // 387 KB on 2026-10-15 (react-dom 176, zod in English 132, site-kit 47, Puck's Render 9); was 1.8 MB.
  assert.ok(runtime < 450_000, `the site runtime is ${runtime} bytes`);
});
