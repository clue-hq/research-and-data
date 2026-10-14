import assert from "node:assert/strict";
import { test } from "node:test";
import { foreignHostImports, hostExportNames, hostModules, shimSource } from "../src/section-host";

test("every host hands over every export its library has, so a section loads the same everywhere", () => {
  const modules = hostModules();
  const react = hostExportNames(modules.react);
  for (const name of ["cache", "use", "useState", "useActionState", "startTransition"]) assert.ok(react.includes(name), name);
  assert.ok(hostExportNames(modules.zod).includes("toJSONSchema"));
  assert.ok(hostExportNames(modules["react/jsx-runtime"]).includes("jsx"));
  assert.ok(!react.includes("default"));
  assert.deepEqual(react, [...react].sort());
});

test("a shim re-exports the host's own copy and names a missing host plainly", () => {
  const source = shimSource("react", ["useState", "cache"]);
  assert.ok(source.includes('globalThis.__clueSectionHost && globalThis.__clueSectionHost["react"]'));
  assert.ok(source.includes("export const { useState, cache } = m;"));
  assert.ok(source.includes("export default m.default ?? m;"));
});

test("a named import the host does not have is refused by name", () => {
  const ok = 'import { useState as s } from "react";\nimport { z, toJSONSchema } from "zod";\nimport { jsx } from "react/jsx-runtime";';
  assert.deepEqual(foreignHostImports(ok), []);
  const bad = 'import { useStat, cache } from "react";\nimport { zz } from "zod";';
  assert.deepEqual(foreignHostImports(bad), [
    'the module imports "useStat" from "react", which react does not export',
    'the module imports "zz" from "zod", which zod does not export',
  ]);
});
