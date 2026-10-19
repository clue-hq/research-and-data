// Builds the site editor into dist/: the browser bundle, its stylesheet, the import-map shims, the
// one HTML page, and the Node server bundle. React is always the production build — the editor's
// policy is the same in dev and production, and production React needs no eval.
import { createHash } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import tailwind from "@tailwindcss/postcss";
import { build } from "esbuild";
import postcss from "postcss";
import { editorThemeCss } from "@clue/site-kit";
import { hostExportNames, hostModules, shimSource, type HostSpecifier } from "@clue/site-kit/section-host";

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const DIST = path.join(ROOT, "dist");
const STYLES = path.join(ROOT, "src/client/styles.css");

// What a compiled agent section may import: every export of the editor's own react,
// react/jsx-runtime and zod, decided once in site-kit's section-host (review finding K2-1).
const HOST = hostModules();
export const SHIMS: Record<string, { names: readonly string[]; specifier: HostSpecifier }> = {
  "react-jsx-runtime.mjs": { names: hostExportNames(HOST["react/jsx-runtime"]), specifier: "react/jsx-runtime" },
  "react.mjs": { names: hostExportNames(HOST.react), specifier: "react" },
  "zod.mjs": { names: hostExportNames(HOST.zod), specifier: "zod" },
};

export const IMPORT_MAP = JSON.stringify({
  imports: { react: "/shims/react.mjs", "react/jsx-runtime": "/shims/react-jsx-runtime.mjs", zod: "/shims/zod.mjs" },
});

export { shimSource };

export function pageHtml(scriptName: string, styleName: string): string {
  return [
    "<!doctype html>",
    '<html lang="en">',
    "<head>",
    '<meta charset="utf-8">',
    '<meta name="viewport" content="width=device-width, initial-scale=1">',
    '<meta name="clue-app-origin" content="%APP_ORIGIN%">',
    "<title>Site editor</title>",
    `<link rel="stylesheet" href="/assets/${styleName}">`,
    `<script type="importmap" nonce="%NONCE%">${IMPORT_MAP}</script>`,
    `<script type="module" src="/assets/${scriptName}"></script>`,
    "</head>",
    '<body><div id="root"></div></body>',
    "</html>",
    "",
  ].join("\n");
}

const THEME_MARKER = "/* @clue-brand-theme */";

export async function compileStyles(): Promise<string> {
  const written = await fs.readFile(STYLES, "utf8");
  if (!written.includes(THEME_MARKER)) throw new Error(`${STYLES} lost its ${THEME_MARKER} line`);
  const source = written.replace(THEME_MARKER, editorThemeCss());
  const result = await postcss([tailwind({ base: ROOT })]).process(source, { from: STYLES });
  return result.css;
}

const shortHash = (text: string) => createHash("sha256").update(text).digest("hex").slice(0, 12);

export async function buildClient(): Promise<void> {
  const result = await build({
    bundle: true,
    define: { "process.env.NODE_ENV": '"production"' },
    entryPoints: [path.join(ROOT, "src/client/main.tsx")],
    format: "esm",
    jsx: "automatic",
    logLevel: "error",
    minify: true,
    platform: "browser",
    target: "es2022",
    write: false,
  });
  const script = result.outputFiles[0].text;
  const style = await compileStyles();
  const scriptName = `editor-${shortHash(script)}.js`;
  const styleName = `editor-${shortHash(style)}.css`;
  await fs.rm(path.join(DIST, "assets"), { force: true, recursive: true });
  await fs.mkdir(path.join(DIST, "assets"), { recursive: true });
  await fs.mkdir(path.join(DIST, "shims"), { recursive: true });
  await fs.writeFile(path.join(DIST, "assets", scriptName), script);
  await fs.writeFile(path.join(DIST, "assets", styleName), style);
  for (const [file, shim] of Object.entries(SHIMS)) {
    await fs.writeFile(path.join(DIST, "shims", file), shimSource(shim.specifier, shim.names));
  }
  await fs.writeFile(path.join(DIST, "index.html"), pageHtml(scriptName, styleName));
}

export async function buildServer(): Promise<void> {
  await build({
    bundle: true,
    entryPoints: [path.join(ROOT, "src/server/main.ts")],
    format: "esm",
    logLevel: "error",
    outfile: path.join(DIST, "server.mjs"),
    platform: "node",
    target: "node22",
  });
}

export async function buildAll(): Promise<void> {
  await buildClient();
  await buildServer();
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await buildAll();
  console.log(`site editor built into ${DIST}`);
}
