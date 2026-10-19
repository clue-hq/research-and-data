// Compile one agent-written section (Wave 2 Lane B, Contract 4).
//
// Usage: node --import tsx bin/compile-section.ts < input.json
// Reads {"name": string, "source": string, "brand": BrandData, "interactive"?: boolean} from stdin
// (interactive: the workspace's sites publish live, so the check allows state, effects, handlers and
// timers; see src/check-section.ts) and prints ONE JSON line:
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
import { foreignHostImports, HOST_SPECIFIERS } from "../src/section-host";
import { tailwindThemeCss } from "../src/theme";

const NAME = /^[A-Z][A-Za-z0-9]{2,40}$/;
/** The only imports a compiled module may keep; each host provides them (src/section-host.ts). */
export { HOST_SPECIFIERS } from "../src/section-host";
const PACKAGE = fileURLToPath(new URL("..", import.meta.url));

export type Compiled =
  | { ok: true; name: string; moduleJs: string; tailwindTheme: string }
  | { ok: false; name: string; errors: string[] };

export type CompileInput = { name: string; source: string; brand: BrandData; interactive?: boolean };

export async function compileSection(input: CompileInput): Promise<Compiled> {
  const { name, source, brand } = input;
  const fail = (errors: string[]): Compiled => ({ ok: false, name, errors });
  if (!NAME.test(name)) return fail([`section name "${name}" is not PascalCase letters and digits`]);
  // The A9 rewrite (Lane A Task 6b): checked against this brand's looks, surfaces and motion classes.
  const errors = lint(source, { ...lintOptionsFor(brand), interactive: input.interactive === true });
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
    const bundled = await bundleSection(checked);
    if (!bundled.ok) return fail(bundled.errors);
    const { moduleJs } = bundled;
    const imports = [...moduleJs.matchAll(/(?:^|\n)\s*import\s[^"']*["']([^"']+)["']/g)].map((m) => m[1]);
    const foreign = imports.filter((specifier) => !(HOST_SPECIFIERS as readonly string[]).includes(specifier));
    if (foreign.length) {
      return fail(foreign.map((s) => `the module imports "${s}"; the kit arrives as render's second argument, import only its type`));
    }
    const missing = foreignHostImports(moduleJs);
    if (missing.length) return fail(missing);
    return { ok: true, name, moduleJs, tailwindTheme: tailwindThemeCss(brand) };
  } finally {
    fs.rmSync(checkDir, { recursive: true, force: true });
  }
}

/** Review S5-1: the bundler resolves nothing but the section itself. Every other module is either one
 * a host provides (left as an import) or refused, so no file on the server can be read into a module
 * whatever the check missed. "@/*" stays external so a value import of the kit is caught after the
 * build instead of bundling the host's own sections into the module; type imports are erased. */
export async function bundleSection(entry: string): Promise<{ ok: true; moduleJs: string } | { ok: false; errors: string[] }> {
  const external = (specifier: string) => (HOST_SPECIFIERS as readonly string[]).includes(specifier) || specifier.startsWith("@/");
  try {
    const bundled = await build({
      entryPoints: [entry],
      bundle: true,
      write: false,
      format: "esm",
      jsx: "automatic",
      platform: "neutral",
      target: "es2022",
      logLevel: "silent",
      plugins: [
        {
          name: "section-only",
          setup(builder) {
            builder.onResolve({ filter: /.*/ }, (args) => {
              if (args.kind === "entry-point") return undefined;
              if (external(args.path)) return { external: true, path: args.path };
              return { errors: [{ text: `"${args.path}" is not allowed; a section imports only zod, react types and @/puck/agent-kit` }] };
            });
          },
        },
      ],
    });
    // esbuild opens the module with a comment naming the checked file's path; dropped so the bytes
    // (and so the digest) depend on the source alone.
    return { ok: true, moduleJs: bundled.outputFiles[0].text.replace(/^\/\/ [^\n]*\n/, "") };
  } catch (error) {
    const failures = (error as { errors?: { text: string }[] }).errors;
    return { ok: false, errors: failures?.length ? failures.map((failure) => failure.text) : [String(error)] };
  }
}

async function main() {
  let raw = "";
  for await (const chunk of process.stdin) raw += chunk;
  const input = JSON.parse(raw) as CompileInput;
  console.log(JSON.stringify(await compileSection(input)));
}

if (process.argv[1]?.endsWith("compile-section.ts")) await main();
