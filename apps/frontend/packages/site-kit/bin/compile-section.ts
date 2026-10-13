// Compile one agent-written section (Wave 2 Lane B, Contract 4).
//
// Usage: node --import tsx bin/compile-section.ts < input.json
// Reads {"name": string, "source": string, "brand": BrandData} from stdin and prints ONE JSON line:
//   {"ok": true, "name", "moduleJs", "tailwindTheme"}  or  {"ok": false, "name", "errors": [string]}
//
// The check is site-kit's own: the lint (brand tokens, banned names, allowed imports; the brand's
// extra surfaces count as its own), then the type check. The bundle is esbuild's: ESM, the automatic
// JSX runtime, react / react/jsx-runtime / zod left as imports each host provides. The module is
// NEVER imported here (D2): its props schema is read in the design API's hardened render page
// (lumen_api.site_render.read_section_schema, through design_record_site_section).
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import type { BrandData } from "../src/brand";
import { lint, lintOptionsFor, typeCheck } from "../src/check-section";
import { tailwindThemeCss } from "../src/theme";

const NAME = /^[A-Z][A-Za-z0-9]{2,40}$/;
/** The only imports a compiled module may keep; each host (editor, renderer) provides them. */
export const HOST_SPECIFIERS = ["react", "react/jsx-runtime", "zod"];
const PACKAGE = fileURLToPath(new URL("..", import.meta.url));

export type Compiled =
  | { ok: true; name: string; moduleJs: string; tailwindTheme: string }
  | { ok: false; name: string; errors: string[] };

export async function compileSection(input: { name: string; source: string; brand: BrandData }): Promise<Compiled> {
  const { name, source, brand } = input;
  const fail = (errors: string[]): Compiled => ({ ok: false, name, errors });
  if (!NAME.test(name)) return fail([`section name "${name}" is not PascalCase letters and digits`]);
  // The A9 rewrite (Lane A Task 6b): checked against this brand's looks, surfaces and motion classes.
  const errors = lint(source, lintOptionsFor(brand));
  if (errors.length) return fail(errors);

  // Type-checked in a throwaway folder inside the package (where zod and react resolve), never
  // next to a file the app imports; removed afterwards. `.section-check/` is git-ignored.
  const checkDir = path.join(PACKAGE, ".section-check", crypto.randomUUID());
  fs.mkdirSync(checkDir, { recursive: true });
  try {
    const checked = path.join(checkDir, `${name}.tsx`);
    fs.writeFileSync(checked, source);
    errors.push(...typeCheck(checked));
    if (errors.length) return fail(errors);
    const bundled = await build({
      entryPoints: [checked],
      bundle: true,
      write: false,
      format: "esm",
      jsx: "automatic",
      platform: "neutral",
      target: "es2022",
      // "@/*" stays external so a value import of the kit is caught below instead of bundling the
      // host's own sections into the module; type imports are erased either way.
      external: [...HOST_SPECIFIERS, "@/*"],
      logLevel: "silent",
    });
    // esbuild opens the module with a comment naming the checked file's path; dropped so the bytes
    // (and so the digest) depend on the source alone.
    const moduleJs = bundled.outputFiles[0].text.replace(/^\/\/ [^\n]*\n/, "");
    const imports = [...moduleJs.matchAll(/(?:^|\n)\s*import\s[^"']*["']([^"']+)["']/g)].map((m) => m[1]);
    const foreign = imports.filter((specifier) => !HOST_SPECIFIERS.includes(specifier));
    if (foreign.length) {
      return fail(foreign.map((s) => `the module imports "${s}"; the kit arrives as render's second argument, import only its type`));
    }
    return { ok: true, name, moduleJs, tailwindTheme: tailwindThemeCss(brand) };
  } finally {
    fs.rmSync(checkDir, { recursive: true, force: true });
  }
}

async function main() {
  let raw = "";
  for await (const chunk of process.stdin) raw += chunk;
  const input = JSON.parse(raw) as { name: string; source: string; brand: BrandData };
  console.log(JSON.stringify(await compileSection(input)));
}

if (process.argv[1]?.endsWith("compile-section.ts")) await main();
