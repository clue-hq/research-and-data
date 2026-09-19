import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import test from "node:test";

function source(path: string) {
  return readFileSync(new URL(path, import.meta.url), "utf8");
}

test("the setting-up screen names only the new onboarding lane", () => {
  const root = new URL("../", import.meta.url);
  const offenders: string[] = [];
  const walk = (dir: URL) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const child = new URL(entry.name + (entry.isDirectory() ? "/" : ""), dir);
      if (entry.isDirectory()) walk(child);
      else if (/\.(ts|tsx)$/.test(entry.name) && /stage0\/setup/.test(readFileSync(child, "utf8"))) offenders.push(child.pathname);
    }
  };
  walk(root);
  assert.deepEqual(offenders, []);
  assert.match(source("../data/setup.ts"), /\/api\/clue\/onboarding\/current/);
  assert.match(source("../data/setup.ts"), /FAST_STEP_KINDS = \["overview", "lineup", "reviews", "synthesis"\]/);
  assert.match(source("../hooks/use-setup-progress.ts"), /window\.location\.replace\("\/session\/establish"\)/);
});
