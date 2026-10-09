// D2 spike (Task 4): compile a section the agent wrote into a module stored per workspace.
//
// Usage: npx tsx scripts/compile-section.ts <workspace> <file.tsx> [--into <site>]
//
// Runs the section check (lint, then the type check), bundles the file with esbuild (ESM, the
// automatic JSX runtime, react / react/jsx-runtime / zod left as imports the host provides),
// writes data/compiled/<workspace>/<sha256>.mjs and prints {name, digest, propsSchema, ms}.
// The digest is the sha256 of the module's bytes, so a module is content-addressed. --into adds
// {name: digest} to data/sites/<site>.json's agentSections (the document's agent_sections in B6)
// and stamps the site's workspace.
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { build } from "esbuild";
import { z } from "zod";
import { lint, typeCheck } from "./check-section";

const SPIKE = path.resolve(__dirname, "..");
export const WORKSPACE = /^[a-z0-9][a-z0-9-]{0,62}$/;
export const DIGEST = /^[0-9a-f]{64}$/;
const NAME = /^[A-Z][A-Za-z0-9]{2,40}$/;
/** The only imports a compiled module may keep; each host (editor, renderer) provides them. */
export const HOST_SPECIFIERS = ["react", "react/jsx-runtime", "zod"];

export type Compiled =
  | { ok: true; name: string; digest: string; propsSchema: unknown; ms: Record<string, number> }
  | { ok: false; name: string; errors: string[]; ms: Record<string, number> };

export async function compileSection(workspace: string, file: string): Promise<Compiled> {
  const ms: Record<string, number> = {};
  const name = path.basename(file, ".tsx");
  const fail = (errors: string[]): Compiled => ({ ok: false, name, errors, ms });
  if (!WORKSPACE.test(workspace)) return fail([`workspace "${workspace}" is not a workspace id`]);
  if (!NAME.test(name)) return fail([`section name "${name}" is not PascalCase letters and digits`]);
  const source = fs.readFileSync(file, "utf-8");

  let t = performance.now();
  const errors = lint(source);
  ms.lint = Math.round(performance.now() - t);
  if (errors.length) return fail(errors);

  // Type-checked where write_section checks a file (agent-runs/ is git-ignored and outside the
  // app), so the check never writes a tsconfig.json next to a section the app imports.
  const checkDir = path.join(SPIKE, "agent-runs", ".section-check", "compile", workspace);
  fs.mkdirSync(checkDir, { recursive: true });
  const checked = path.join(checkDir, `${name}.tsx`);
  fs.writeFileSync(checked, source);
  t = performance.now();
  errors.push(...typeCheck(checked));
  ms.typeCheck = Math.round(performance.now() - t);
  if (errors.length) return fail(errors);

  t = performance.now();
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
  // esbuild opens the module with a comment naming the checked file's path; dropped so the digest
  // depends on the source alone, not on the workspace's check directory.
  const code = bundled.outputFiles[0].text.replace(/^\/\/ [^\n]*\n/, "");
  ms.bundle = Math.round(performance.now() - t);
  const imports = [...code.matchAll(/(?:^|\n)\s*import\s[^"']*["']([^"']+)["']/g)].map((m) => m[1]);
  const foreign = imports.filter((s) => !HOST_SPECIFIERS.includes(s));
  if (foreign.length) return fail(foreign.map((s) => `the module imports "${s}"; the kit arrives as render's second argument, import only its type`));

  const digest = crypto.createHash("sha256").update(code).digest("hex");
  const outDir = path.join(SPIKE, "data", "compiled", workspace);
  fs.mkdirSync(outDir, { recursive: true });
  const out = path.join(outDir, `${digest}.mjs`);
  fs.writeFileSync(out, code);

  // The props schema comes from the stored module itself (which proves it loads in Node).
  // NOTE (finding): this runs the module's top-level code in the compiling process.
  t = performance.now();
  const mod = (await import(pathToFileURL(out).href)) as { schema?: unknown; render?: unknown };
  ms.schema = Math.round(performance.now() - t);
  if (!(mod.schema instanceof z.ZodObject)) return fail(["`schema` must be a zod object"]);
  if (typeof mod.render !== "function") return fail(["`render` must be a function"]);
  return { ok: true, name, digest, propsSchema: z.toJSONSchema(mod.schema), ms };
}

function register(site: string, workspace: string, name: string, digest: string): void {
  const file = path.join(SPIKE, "data", "sites", `${site}.json`);
  const stored = JSON.parse(fs.readFileSync(file, "utf-8")) as { workspace?: string; agentSections?: Record<string, string> };
  if (stored.workspace && stored.workspace !== workspace) throw new Error(`site ${site} belongs to workspace ${stored.workspace}`);
  stored.workspace = workspace;
  stored.agentSections = { ...(stored.agentSections ?? {}), [name]: digest };
  fs.writeFileSync(file, JSON.stringify(stored, null, 2));
}

async function main() {
  const [workspace, file] = process.argv.slice(2);
  const intoAt = process.argv.indexOf("--into");
  const started = performance.now();
  const result = await compileSection(workspace ?? "", path.resolve(file ?? ""));
  result.ms.total = Math.round(performance.now() - started);
  if (result.ok && intoAt > 0) register(process.argv[intoAt + 1], workspace, result.name, result.digest);
  if (result.ok) console.log(JSON.stringify({ name: result.name, digest: result.digest, propsSchema: result.propsSchema, ms: result.ms }));
  else console.log(JSON.stringify({ name: result.name, ok: false, errors: result.errors, ms: result.ms }));
  if (!result.ok) process.exitCode = 1;
}

if (process.argv[1]?.endsWith("compile-section.ts")) main();
