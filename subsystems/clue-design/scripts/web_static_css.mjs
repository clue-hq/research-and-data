/**
 * Static Tailwind v4 compile for website-mode export/publish (P4).
 *
 * Usage: node scripts/web_static_css.mjs <html_file> <input_css_file> <out_css_file>
 *
 * Compiles the utility classes actually present in <html_file> against the
 * document's theme (<input_css_file> = `@import "tailwindcss";` + the @theme
 * block of --color-* tokens) into one static stylesheet. Runs as a build
 * step, never in a hot path. Uses the editor app's existing Tailwind v4
 * toolchain (@tailwindcss/node compile + @tailwindcss/oxide scanner) — the
 * same engine the editor's browser runtime uses, so exported pages style
 * identically to the canvas.
 *
 * Exit codes: 0 ok; 1 usage; 2 compile failure (message on stderr).
 */
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const editorModules = resolve(repoRoot, "apps/editor/node_modules");

const [htmlFile, inputCssFile, outCssFile] = process.argv.slice(2);
if (!htmlFile || !inputCssFile || !outCssFile) {
  console.error("usage: node scripts/web_static_css.mjs <html_file> <input_css_file> <out_css_file>");
  process.exit(1);
}

try {
  const { compile } = await import(
    pathToFileURL(resolve(editorModules, "@tailwindcss/node/dist/index.js")).href
  );
  const { Scanner } = await import(
    pathToFileURL(resolve(editorModules, "@tailwindcss/oxide/index.js")).href
  );

  const inputCss = readFileSync(resolve(inputCssFile), "utf8");
  // `base` anchors the `@import "tailwindcss"` resolution to the editor app,
  // where the tailwindcss package is installed.
  const compiler = await compile(inputCss, {
    base: resolve(repoRoot, "apps/editor"),
    onDependency: () => {},
  });

  const htmlPath = resolve(htmlFile);
  const scanner = new Scanner({
    sources: [{ base: dirname(htmlPath), pattern: htmlPath.split("/").pop(), negated: false }],
  });
  const css = compiler.build(scanner.scan());
  writeFileSync(resolve(outCssFile), css, "utf8");
} catch (error) {
  console.error(`web_static_css: compile failed: ${error && error.message ? error.message : error}`);
  process.exit(2);
}
