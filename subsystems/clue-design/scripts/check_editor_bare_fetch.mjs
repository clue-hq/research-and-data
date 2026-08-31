#!/usr/bin/env node
/* Editor lumenFetch guard (O4 workspace seam).
 *
 * RULE: production editor code talks to the design API ONLY through
 * `lumenFetch` (src/engine/editorConfig.ts) — the wrapper that attaches the
 * `X-Workspace-Id` header the strict O4 seam requires (401
 * `workspace.header_required` otherwise). A bare global `fetch` ships a
 * headerless transport that 401s in every real browser while every vitest
 * suite stays green (tests inject `fetchImpl` or stub the global).
 *
 * The guard flags BOTH token shapes of the global:
 *   - the call form        `fetch(...)`
 *   - the value form       `= fetch`, `?? fetch`, `(fetch`, `, fetch`, `: fetch`
 * The split between those two shapes is literally how the bug class shipped:
 * the D2.5A migration enumerated API-calling modules by grepping `fetch(`,
 * and documentStore/brandHub — whose only fetch token was the parenless
 * default `= fetch` — were silently skipped and 401'd in production for four
 * days. (`typeof fetch` stays legal everywhere: it is a type/feature probe,
 * never a transport.)
 *
 * LEVEL: error. Allowlisted files each carry an in-code justification at the
 * fetch site — a new exemption must add BOTH the list entry here and the
 * why-exempt comment there.
 *
 * Usage: node scripts/check_editor_bare_fetch.mjs   (repo root or apps/editor)
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, relative } from "node:path";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const srcRoot = join(repoRoot, "apps/editor/src");

// Files allowed to reach the global fetch, each documented at the site:
const ALLOWLIST = new Set([
  // Defines lumenFetch — the ONE sanctioned wrapper around the global.
  "apps/editor/src/engine/editorConfig.ts",
  // SSE stream GET authenticated by a single-use token minted THROUGH
  // lumenFetch; the workspace is read off the token row, never the client.
  "apps/editor/src/engine/runEventStream.ts",
  // /asset-store/{digest} public bytes: fetched from origin-"null" srcdoc
  // iframes where a custom header would force a CORS preflight the wildcard
  // response cannot satisfy.
  "apps/editor/src/engine/canvaskit/imageCache.ts",
  // Loads Next static assets (/canvaskit/*, font files), not the design API.
  "apps/editor/src/engine/canvaskit/loadCanvasKit.ts",
  // Hits only /build-info — one of the O4 seam's three header-exempt routes
  // (the engine handshake runs before any workspace context exists).
  "apps/editor/src/engine/wasmEngine.ts",
]);

// The global used as a transport. Deliberately NOT matched: `typeof fetch`
// (type/feature probe), identifiers merely containing the word
// (fetchImpl, lumenFetch, doFetch), and `<obj>.fetch` on non-global objects.
const BARE_FETCH_RE =
  /(?<![.\w$])fetch\s*\(|[=,(?:]\s*fetch\b|(?:globalThis|window|self)\.fetch\b/g;

/** @param {string} dir */
function sourceFiles(dir) {
  /** @type {string[]} */
  const out = [];
  for (const entry of readdirSync(dir)) {
    if (entry === "node_modules" || entry === ".next" || entry === "__tests__") continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      // src/test/ holds vitest setup, not production transport.
      if (relative(srcRoot, full) === "test") continue;
      out.push(...sourceFiles(full));
    } else if (/\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry)) {
      out.push(full);
    }
  }
  return out;
}

/** Blank out comments while preserving line numbers ('://' stays intact). */
function stripComments(content) {
  const noBlock = content.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, " "));
  return noBlock
    .split("\n")
    .map((line) => line.replace(/(^|[^:])\/\/.*$/, "$1"));
}

let violations = 0;
const perFile = [];
for (const file of sourceFiles(srcRoot)) {
  const rel = relative(repoRoot, file);
  if (ALLOWLIST.has(rel)) continue;
  const lines = stripComments(readFileSync(file, "utf8"));
  let fileCount = 0;
  lines.forEach((code, i) => {
    const matches = code.match(BARE_FETCH_RE);
    if (matches) {
      fileCount += matches.length;
      if (process.env.FETCH_GUARD_VERBOSE) {
        console.log(`  ${rel}:${i + 1}  ${code.trim()}`);
      }
    }
  });
  if (fileCount) {
    violations += fileCount;
    perFile.push(`  ${rel}: ${fileCount}`);
  }
}

if (violations === 0) {
  console.log("editor lumenFetch guard: clean (the global fetch lives only behind lumenFetch).");
  process.exit(0);
}

console.log(
  `editor lumenFetch guard: error — ${violations} bare global-fetch use(s) outside the allowlist:`,
);
console.log(perFile.join("\n"));
console.log(
  "  (route API calls through lumenFetch from engine/editorConfig.ts — the O4 seam 401s\n" +
    "  headerless requests; a genuine exemption needs an allowlist entry AND a why-exempt\n" +
    "  comment at the site. Set FETCH_GUARD_VERBOSE=1 for lines.)",
);
process.exit(1);
