import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

test("the scene engine slice reads no ambient environment", () => {
  const root = join(dirname(fileURLToPath(import.meta.url)), "..");
  const offenders: string[] = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (entry.isDirectory()) { if (entry.name !== "__tests__") walk(join(dir, entry.name)); continue; }
      if (!entry.name.endsWith(".ts")) continue;
      const source = readFileSync(join(dir, entry.name), "utf8");
      if (/process\.env|NEXT_PUBLIC_/.test(source)) offenders.push(entry.name);
      if (/localhost:8000|X-Workspace-Id/.test(source)) offenders.push(`${entry.name} (direct-API residue)`);
    }
  };
  walk(root);
  assert.deepEqual(offenders, []);
});
