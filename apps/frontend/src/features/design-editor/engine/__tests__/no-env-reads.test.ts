import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

// W1.1 guard: the extracted engine is configured by injection only. A
// process.env or NEXT_PUBLIC_* read sneaking back in would silently rebind
// the engine to ambient environment (the dev-harness pattern this extraction
// retires) and break the BFF auth contract (config.ts).
test("the engine package reads no ambient environment", () => {
  const engineDir = join(dirname(fileURLToPath(import.meta.url)), "..");
  const offenders: string[] = [];
  for (const entry of readdirSync(engineDir, { withFileTypes: true })) {
    if (!entry.isFile() || !entry.name.endsWith(".ts")) continue;
    const source = readFileSync(join(engineDir, entry.name), "utf8");
    if (/process\.env|NEXT_PUBLIC_/.test(source)) offenders.push(entry.name);
  }
  assert.deepEqual(
    offenders,
    [],
    `engine modules must not read ambient environment: ${offenders.join(", ")}`,
  );
});
