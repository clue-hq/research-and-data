// Lane B Task 15 (Contract 4): an agent-written section is checked, bundled and given its
// Tailwind theme in Node, and never imported (D2).
import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";
import { compileSection, HOST_SPECIFIERS } from "../bin/compile-section";
import { garner } from "./fixtures/garner";

// The spike's writing-a-section example, verbatim (the check-section tests use the same file).
const EXAMPLE = fs.readFileSync(new URL("./fixtures/section-example.tsx", import.meta.url), "utf-8");
const CHECK_DIR = new URL("../.section-check/", import.meta.url);

test("a valid section compiles to a module that imports only what the host provides", async () => {
  const result = await compileSection({ name: "QuoteBand", source: EXAMPLE, brand: garner() });
  assert.equal(result.ok, true, JSON.stringify(result));
  if (!result.ok) return;
  const imports = [...result.moduleJs.matchAll(/(?:^|\n)\s*import\s[^"']*["']([^"']+)["']/g)].map((m) => m[1]);
  assert.ok(imports.every((specifier) => HOST_SPECIFIERS.includes(specifier)), imports.join(", "));
  assert.match(result.moduleJs, /export\s*\{/);
  assert.ok(result.tailwindTheme.startsWith("@theme inline {"));
});

test("the same source compiles to the same bytes, so the digest is the content's", async () => {
  const a = await compileSection({ name: "QuoteBand", source: EXAMPLE, brand: garner() });
  const b = await compileSection({ name: "QuoteBand", source: EXAMPLE, brand: garner() });
  assert.ok(a.ok && b.ok);
  if (a.ok && b.ok) assert.equal(a.moduleJs, b.moduleJs);
});

test("a brand-token error is refused before the type check runs", async () => {
  const source = EXAMPLE.replace("mt-6 font-body text-body text-ink-secondary", "mt-6 text-emerald-600");
  const result = await compileSection({ name: "QuoteBand", source, brand: garner() });
  assert.equal(result.ok, false);
  if (!result.ok) assert.ok(result.errors.some((e) => e.includes('class "text-emerald-600"')), result.errors.join("; "));
});

test("a type error is refused", async () => {
  const source = EXAMPLE.replace("export function render", 'const wrong: number = "seven";\nexport function render');
  const result = await compileSection({ name: "QuoteBand", source, brand: garner() });
  assert.equal(result.ok, false);
  if (!result.ok) assert.ok(result.errors.some((e) => e.startsWith("type error:")), result.errors.join("; "));
});

test("a bad name is refused and the check folder is left empty", async () => {
  const result = await compileSection({ name: "quoteBand", source: EXAMPLE, brand: garner() });
  assert.deepEqual(result, { ok: false, name: "quoteBand", errors: ['section name "quoteBand" is not PascalCase letters and digits'] });
  await compileSection({ name: "QuoteBand", source: EXAMPLE, brand: garner() });
  const left = fs.existsSync(CHECK_DIR) ? fs.readdirSync(CHECK_DIR).filter((entry) => entry.length === 36) : [];
  assert.deepEqual(left, []);
});
