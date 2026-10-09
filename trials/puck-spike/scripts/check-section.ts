// The check a section written by the agent must pass before it joins its site (E5).
//
// Usage: npx tsx scripts/check-section.ts <file.tsx>
// Prints {"ok": bool, "errors": [...], "props": <JSON Schema of the section's props>} as JSON.
//
// Structure is free; style is the brand's. Refused: colour values, Tailwind's own palette colours,
// Tailwind's default type sizes, families and weights, bracketed custom values for colour, type
// or corners (layout measures such as max-w-[30ch] are fine), inline styles, className or style
// in the section's props, imports other than zod, react types and the kit, and the banned names
// below (page globals, network, eval, raw HTML, storage, timers, event handlers). The file must export
// `schema` (a zod object) and `render`, and must type-check.
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import ts from "typescript";
import { z } from "zod";

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
// section's text or strings never count. A guardrail against the obvious, not a sandbox: see
// RUNTIME-SECTIONS.md for what it cannot catch.
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
  const spike = path.resolve(__dirname, "..");
  fs.writeFileSync(
    path.join(dir, "tsconfig.json"),
    JSON.stringify({
      extends: path.relative(dir, path.join(spike, "tsconfig.json")),
      compilerOptions: { incremental: false, noEmit: true },
      include: [path.basename(file), path.relative(dir, path.join(spike, "next-env.d.ts"))],
      // The spike's tsconfig excludes agent-runs/, where this file is checked; inheriting that
      // exclude would silently type-check nothing.
      exclude: [],
    }),
  );
  try {
    execFileSync(path.join(spike, "node_modules", ".bin", "tsc"), ["-p", path.join(dir, "tsconfig.json")], { cwd: spike, stdio: "pipe" });
    return [];
  } catch (error) {
    const out = String((error as { stdout?: Buffer }).stdout ?? error);
    return out.split("\n").filter((l) => l.includes("error TS")).slice(0, 8).map((l) => `type error: ${l.replace(/^.*?\(/, "(")}`);
  }
}

async function main() {
  const file = path.resolve(process.argv[2] ?? "");
  const source = fs.readFileSync(file, "utf-8");
  const errors = lint(source);
  if (!errors.length) errors.push(...typeCheck(file));
  let props: unknown = null;
  if (!errors.length) {
    const mod = (await import(pathToFileURL(file).href)) as { schema?: unknown; render?: unknown };
    if (!(mod.schema instanceof z.ZodObject)) errors.push("`schema` must be a zod object (z.object({...}).strict())");
    else {
      const keys = Object.keys(mod.schema.shape);
      for (const key of ["className", "style"]) if (keys.includes(key)) errors.push(`the props may not include "${key}"`);
      for (const key of ["id", "surface"]) if (!keys.includes(key)) errors.push(`the props need "${key}" (every section has an id and a surface)`);
      props = z.toJSONSchema(mod.schema);
    }
    if (typeof mod.render !== "function") errors.push("`render` must be a function (props, kit) => JSX");
  }
  console.log(JSON.stringify({ ok: errors.length === 0, errors, props }));
}

if (process.argv[1]?.endsWith("check-section.ts")) main();
