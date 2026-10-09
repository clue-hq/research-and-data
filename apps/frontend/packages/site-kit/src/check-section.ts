// The check a section written by the agent must pass before it joins its site (E5).
//
// Usage: npx tsx src/check-section.ts <file.tsx>
// Prints {"ok": bool, "errors": [...], "props": <JSON Schema of the section's props>} as JSON.
//
// Structure is free; style is the brand's. Refused: colour values, Tailwind's own palette colours,
// Tailwind's default type sizes, families and weights, bracketed custom values for colour, type
// or corners (layout measures such as max-w-[30ch] are fine), inline styles, className or style
// in the section's props, imports other than zod, react types and the kit. The file must export
// `schema` (a zod object) and `render`, and must type-check.
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
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
