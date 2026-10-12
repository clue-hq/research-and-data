// The check a section written by the agent must pass before it joins its site (E5).
//
// Usage: npx tsx src/check-section.ts <file.tsx>
// Prints {"ok": bool, "errors": [...]} as JSON.
//
// Structure is free; style is the brand's. Refused: colour values, Tailwind's own palette colours,
// Tailwind's default type sizes, families and weights, bracketed custom values for colour, type
// or corners (layout measures such as max-w-[30ch] are fine), inline styles, imports other than
// zod, react types and the kit, and the banned names below (page globals, network, eval, raw
// HTML, storage, timers, event handlers). The file must export `schema` (a zod object) and
// `render`, and must type-check.
//
// D2 (founder, 2026-10-09 and 2026-10-11): this check NEVER imports the section. The props schema,
// and the rules about it (an id and a surface, no className or style), are read inside the design
// API's hardened render page (lumen_api.site_render.read_section_schema), never in a platform
// process.
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const ALLOWED_IMPORTS = new Set(["zod", "react", "@/puck/agent-kit"]);
const PALETTE =
  "slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose";
const COLOUR_UTILITY = "text|bg|border|fill|stroke|ring|outline|decoration|divide|from|via|to|accent|caret|shadow|placeholder";
const RULES: { pattern: RegExp; why: string }[] = [
  { pattern: new RegExp(`^(${COLOUR_UTILITY})-(${PALETTE})-\\d{2,3}(\\/\\d+)?$`), why: "a Tailwind palette colour; use the brand's text-ink-*, bg-surface-* or border-line-*" },
  { pattern: new RegExp(`^(${COLOUR_UTILITY})-(black|white)(\\/\\d+)?$`), why: "a fixed colour; use the brand's text-ink-*, bg-surface-* or border-line-*" },
  { pattern: /^text-(xs|sm|base|lg|xl|[2-9]xl)$/, why: "a Tailwind type size; use a brand type role (text-title, text-body…)" },
  { pattern: /^font-(sans|serif|mono|thin|extralight|light|normal|medium|semibold|bold|extrabold|black)$/, why: "a Tailwind font or weight; use a brand type role (font-title, font-body…)" },
  { pattern: /^(text|bg|border|fill|stroke|ring|outline|decoration|font|leading|tracking|rounded|shadow|from|via|to)-\[/, why: "a custom colour, type or corner value; use the brand's tokens" },
];

// D2 spike (Task 4): names a section may not use, wherever they appear in its code (a variable, a
// property such as document.cookie, an object key). Read from the syntax tree, so the words in a
// section's text or strings never count. A guardrail against the obvious, not a sandbox: the
// hardened render page is the boundary (trials/puck-spike/RUNTIME-SECTIONS.md).
const BANNED: Record<string, string> = {
  window: "reaches the page outside the section",
  document: "reaches the page outside the section",
  globalThis: "reaches the page outside the section",
  fetch: "is a network call",
  XMLHttpRequest: "is a network call",
  WebSocket: "is a network call",
  eval: "runs code the check never saw",
  Function: "runs code the check never saw",
  dangerouslySetInnerHTML: "writes raw HTML",
  localStorage: "reads the visitor's storage",
  cookie: "reads the visitor's cookies",
  setTimeout: "is a timer; a section renders once from its props",
  setInterval: "is a timer; a section renders once from its props",
};

function bannedNames(source: string): string[] {
  const errors: string[] = [];
  const seen = new Set<string>();
  const add = (message: string) => {
    if (!seen.has(message)) {
      seen.add(message);
      errors.push(message);
    }
  };
  const file = ts.createSourceFile("section.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const visit = (node: ts.Node) => {
    if (ts.isIdentifier(node) && Object.hasOwn(BANNED, node.text)) add(`"${node.text}" ${BANNED[node.text]}; a section renders its props and nothing else`);
    if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword) add(`"import(" loads code the check never saw; a section renders its props and nothing else`);
    // An event handler, as a JSX prop or as a key of an object that might be spread into one.
    if (ts.isJsxAttribute(node) || ts.isPropertyAssignment(node) || ts.isShorthandPropertyAssignment(node) || ts.isMethodDeclaration(node)) {
      const name = node.name.getText(file).replace(/^["'`]|["'`]$/g, "");
      if (/^on[A-Z]/.test(name)) add(`"${name}" is an event handler; a section is static`);
    }
    ts.forEachChild(node, visit);
  };
  visit(file);
  return errors;
}

function classTokens(source: string): string[] {
  const strings = [...source.matchAll(/"([^"\n]*)"|'([^'\n]*)'|`([^`]*)`/g)].map((m) => m[1] ?? m[2] ?? m[3] ?? "");
  return strings.flatMap((s) => s.split(/\s+/)).filter(Boolean).map((t) => t.split(":").pop() ?? t);
}

export function lint(source: string): string[] {
  const errors: string[] = [];
  for (const m of source.matchAll(/import\s+(?:type\s+)?[^"']*from\s+["']([^"']+)["']/g)) {
    if (!ALLOWED_IMPORTS.has(m[1])) errors.push(`import "${m[1]}" is not allowed; a section imports only zod, react types and @/puck/agent-kit`);
  }
  const withoutHrefs = source.replace(/href=\{?["'`][^"'`]*["'`]\}?/g, "");
  for (const m of withoutHrefs.matchAll(/#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b/g)) errors.push(`colour value ${m[0]}; use the brand's colour tokens`);
  for (const m of source.matchAll(/\b(rgba?|hsla?|oklch|oklab|lab|lch)\(/g)) errors.push(`colour function ${m[0]}…); use the brand's colour tokens`);
  if (/\bstyle\s*=/.test(source) || /\bstyle\s*:/.test(source)) errors.push("inline style; style only with the brand's classes");
  const seen = new Set<string>();
  for (const token of classTokens(source)) {
    for (const rule of RULES) {
      if (rule.pattern.test(token) && !seen.has(token)) {
        seen.add(token);
        errors.push(`class "${token}" is ${rule.why}`);
      }
    }
  }
  errors.push(...bannedNames(source));
  if (!/export\s+const\s+schema\b/.test(source)) errors.push("the file must export `schema` (a zod object of the section's props)");
  if (!/export\s+function\s+render\b/.test(source)) errors.push("the file must export `function render(props, kit)`");
  return errors;
}

export function typeCheck(file: string): string[] {
  const dir = path.dirname(file);
  // The package's tsconfig maps the kit's import (@/puck/agent-kit) to src/agent-kit.tsx. The file
  // must sit where zod and react resolve (inside apps/frontend), as in the spike.
  const root = fileURLToPath(new URL("..", import.meta.url));
  const tsc = createRequire(import.meta.url).resolve("typescript/bin/tsc");
  fs.writeFileSync(
    path.join(dir, "tsconfig.json"),
    JSON.stringify({
      extends: path.relative(dir, path.join(root, "tsconfig.json")),
      compilerOptions: { incremental: false, noEmit: true },
      include: [path.basename(file)],
      // Inheriting an exclude that covers the file's directory would silently type-check nothing.
      exclude: [],
    }),
  );
  try {
    execFileSync(process.execPath, [tsc, "-p", path.join(dir, "tsconfig.json")], { cwd: root, stdio: "pipe" });
    return [];
  } catch (error) {
    const out = String((error as { stdout?: Buffer }).stdout ?? error);
    return out.split("\n").filter((l) => l.includes("error TS")).slice(0, 8).map((l) => `type error: ${l.replace(/^.*?\(/, "(")}`);
  }
}

function main() {
  const file = path.resolve(process.argv[2] ?? "");
  const source = fs.readFileSync(file, "utf-8");
  const errors = lint(source);
  if (!errors.length) errors.push(...typeCheck(file));
  console.log(JSON.stringify({ ok: errors.length === 0, errors }));
}

if (process.argv[1]?.endsWith("check-section.ts")) main();
