#!/usr/bin/env node
/* Editor no-hex guard (R0 restyle substrate).
 *
 * RULE: literal colors (#hex, rgb(, rgba(, hsl(, hsla()) may live ONLY in the
 * token layer — apps/editor/src/app/tokens.css (and the shipped brand layer
 * apps/editor/src/app/brand/tokens.css). Every other CSS file under
 * apps/editor/src must consume var(--…). This keeps a rebrand a one-file edit.
 *
 * LEVEL: warn (exit 0) while the pre-existing shell debt is cleaned. R0 aliased
 * the legacy chrome/panel/teal token VALUES onto the semantic layer
 * without touching component markup, so styles.css still carries ~133 inline
 * literals in its component rules. R1 migrates that markup to the semantics and
 * removes the literals; when the count hits 0, flip ALLOW_EXISTING to false to
 * make this error-level (new literals then fail the build).
 *
 * Usage: node scripts/check_editor_hex.mjs   (run from repo root or apps/editor)
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, relative } from "node:path";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const srcRoot = join(repoRoot, "apps/editor/src");

// Files allowed to contain literal colors (the token layers).
const ALLOWLIST = new Set([
  "apps/editor/src/app/tokens.css",
  "apps/editor/src/app/brand/tokens.css",
]);

// While pre-existing shell literals are being migrated (R1), stay warn-level.
const ALLOW_EXISTING = true;

const COLOR_RE = /#[0-9a-fA-F]{3,8}\b|(?:rgb|rgba|hsl|hsla)\(/g;

/** @param {string} dir */
function cssFiles(dir) {
  /** @type {string[]} */
  const out = [];
  for (const entry of readdirSync(dir)) {
    if (entry === "node_modules" || entry === ".next") continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...cssFiles(full));
    else if (entry.endsWith(".css")) out.push(full);
  }
  return out;
}

let violations = 0;
const perFile = [];
for (const file of cssFiles(srcRoot)) {
  const rel = relative(repoRoot, file);
  if (ALLOWLIST.has(rel)) continue;
  const lines = readFileSync(file, "utf8").split("\n");
  let fileCount = 0;
  lines.forEach((line, i) => {
    // Ignore comment-only lines to avoid flagging documentation.
    const code = line.replace(/\/\*.*?\*\//g, "");
    const matches = code.match(COLOR_RE);
    if (matches) {
      fileCount += matches.length;
      if (process.env.HEX_GUARD_VERBOSE) {
        console.log(`  ${rel}:${i + 1}  ${line.trim()}`);
      }
    }
  });
  if (fileCount) {
    violations += fileCount;
    perFile.push(`  ${rel}: ${fileCount}`);
  }
}

if (violations === 0) {
  console.log("editor no-hex guard: clean (literals live only in tokens.css).");
  process.exit(0);
}

const header = ALLOW_EXISTING ? "warning" : "error";
console.log(
  `editor no-hex guard: ${header} — ${violations} literal-color occurrence(s) ` +
    `outside the token layer:`,
);
console.log(perFile.join("\n"));
console.log(
  "  (allowed only in tokens.css; use var(--…). Set HEX_GUARD_VERBOSE=1 for lines.)",
);
process.exit(ALLOW_EXISTING ? 0 : 1);
