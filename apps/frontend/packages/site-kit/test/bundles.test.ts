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
