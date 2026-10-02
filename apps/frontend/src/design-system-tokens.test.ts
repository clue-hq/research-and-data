/**
 * Every `--clue-*` custom property the app READS must be DEFINED somewhere the
 * browser will actually load.
 *
 * This test exists because of the D4 design-system port (2026-09-09): the
 * package's `generated/tokens.css` was replaced wholesale with the production
 * design system, which does not define ~48 of the variables the pre-D4 one did.
 * Those live on in `generated/legacy-compat.css` until the CSS re-sync job
 * retires them. The test is the thing that proves nothing lost its definition
 * in the swap, and the thing that will fail if the compat layer is deleted
 * before the features that depend on it are re-synced.
 *
 * Definition sources — all three are loaded by the real app:
 *   1. packages/design-system/generated/tokens.css   (imported in app/layout.tsx)
 *   2. packages/design-system/generated/legacy-compat.css (imported right after)
 *   3. src/app/globals.css — defines a small `:root` block of compatibility
 *      aliases (`--clue-background-neutral: var(--clue-ds-color-bg-neutral)` and
 *      friends). Those are genuine definitions the app relies on, so excluding
 *      this file would make the assertion assert a falsehood.
 *
 * Reference rule: only a `var(--x)` WITHOUT a fallback must resolve. A
 * `var(--x, #b42318)` is optional by the CSS spec — it renders correctly whether
 * or not `--x` exists — so it is not a broken reference.
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(HERE, "..");
const SRC_ROOT = path.join(FRONTEND_ROOT, "src");
const GENERATED = path.join(FRONTEND_ROOT, "packages", "design-system", "generated");

/**
 * Names referenced with no fallback and defined nowhere. Both predate the D4
 * port (they were already dangling against the OLD tokens.css), so they are
 * pinned here rather than papered over: the CSS re-sync job that re-lifts
 * `accounts` and `chat-shell` from the dummy frontend removes them. This set
 * may only ever shrink — the test below fails if an entry stops being dangling.
 */
const KNOWN_DANGLING_PRE_D4 = new Set([
  "--clue-content-default", // src/features/accounts/components/account-workspace-screens.tsx
  "--clue-ds-color-bg-input", // src/features/chat-shell/components/chat-shell.module.css
]);

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === "node_modules" || entry.name === ".next") continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    // Test files are not styling; excluding them also stops this file from
    // matching the `var(--clue-…)` examples in its own comments.
    else if (/\.(css|ts|tsx)$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name)) out.push(full);
  }
  return out;
}

/** `--clue-foo: …` declarations in a CSS file, at any selector/at-rule depth. */
function definedIn(file: string): Set<string> {
  const names = new Set<string>();
  if (!fs.existsSync(file)) return names;
  const text = fs.readFileSync(file, "utf8");
  for (const match of text.matchAll(/(--clue-[a-z0-9-]+)\s*:/g)) names.add(match[1]);
  return names;
}

/**
 * `var(--clue-foo)` reads, keyed by the file:line they appear on. A read with a
 * comma after the name carries a fallback and is skipped.
 */
function referencesUnder(root: string): Map<string, string[]> {
  const found = new Map<string, string[]>();
  for (const file of walk(root)) {
    const lines = fs.readFileSync(file, "utf8").split("\n");
    lines.forEach((line, index) => {
      for (const match of line.matchAll(/var\(\s*(--clue-[a-z0-9-]+)\s*\)/g)) {
        const site = `${path.relative(FRONTEND_ROOT, file)}:${index + 1}`;
        const sites = found.get(match[1]);
        if (sites) sites.push(site);
        else found.set(match[1], [site]);
      }
    });
  }
  return found;
}

const defined = new Set([
  ...definedIn(path.join(GENERATED, "tokens.css")),
  ...definedIn(path.join(GENERATED, "legacy-compat.css")),
  ...definedIn(path.join(SRC_ROOT, "app", "globals.css")),
]);
const referenced = referencesUnder(SRC_ROOT);

test("every --clue-* variable the app reads without a fallback is defined", () => {
  const missing = [...referenced.entries()]
    .filter(([name]) => !defined.has(name) && !KNOWN_DANGLING_PRE_D4.has(name))
    .map(([name, sites]) => `${name}\n    ${sites.slice(0, 3).join("\n    ")}`);
  assert.deepEqual(
    missing,
    [],
    `${missing.length} --clue-* variable(s) are read with no fallback and defined in neither ` +
      `tokens.css, legacy-compat.css, nor globals.css:\n  ${missing.join("\n  ")}`,
  );
});

test("the pre-D4 dangling allowlist may only shrink", () => {
  const resolved = [...KNOWN_DANGLING_PRE_D4].filter((name) => defined.has(name));
  assert.deepEqual(
    resolved,
    [],
    `these names are now defined — delete them from KNOWN_DANGLING_PRE_D4: ${resolved.join(", ")}`,
  );
  const unreferenced = [...KNOWN_DANGLING_PRE_D4].filter((name) => !referenced.has(name));
  assert.deepEqual(
    unreferenced,
    [],
    `these names are no longer read anywhere — delete them from KNOWN_DANGLING_PRE_D4: ${unreferenced.join(", ")}`,
  );
});
