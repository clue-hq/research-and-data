// Builds the site kit's runnable files into dist/, each one file with its dependencies inside,
// so the design API and the fleet workers run them with plain `node` (their image has no
// apps/frontend/node_modules):
//   dist/validate-site.mjs   the validator CLI (bin/validate-site.ts)
//   dist/build-catalog.mjs   the catalog CLI (bin/build-catalog.ts)
//   dist/render-browser.js   the site render inside the hardened Chromium page (src/render-browser.tsx)
//   dist/site-runtime.js     the published page's browser entry, one ES module (src/site-runtime.tsx)
//   dist/site-runtime-shims/{react,react-jsx-runtime,zod}.js
//                            the import-map targets that hand agent sections the runtime's own copies
// Usage: node bin/build-bundles.mjs   (npm run build -w @clue/site-kit)
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { build } from "esbuild";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const dist = path.join(root, "dist");
const banner = { js: "// Built by apps/frontend/packages/site-kit/bin/build-bundles.mjs. Do not edit." };

await Promise.all(
  ["validate-site", "build-catalog"].map((name) =>
    build({
      absWorkingDir: root,
      entryPoints: [`bin/${name}.ts`],
      outfile: path.join(dist, `${name}.mjs`),
      bundle: true,
      platform: "node",
      format: "esm",
      target: "node22",
      legalComments: "none",
      logLevel: "warning",
      banner,
    }),
  ),
);
await build({
  absWorkingDir: root,
  entryPoints: ["src/render-browser.tsx"],
  outfile: path.join(dist, "render-browser.js"),
  bundle: true,
  platform: "browser",
  format: "iife",
  target: "chrome120",
  jsx: "automatic",
  minify: true,
  legalComments: "none",
  define: { "process.env.NODE_ENV": '"production"' },
  logLevel: "warning",
  banner,
});
// Puck's render-only Render loads its rich-text renderer (tiptap and ProseMirror, ~300 KB) lazily,
// for `richtext` fields only, and a one-file bundle would inline it. No site-kit or agent section
// has a richtext field, so the published page's runtime gets a stand-in that says so loudly instead.
const withoutPuckRichText = {
  name: "without-puck-richtext",
  setup(pluginBuild) {
    pluginBuild.onResolve({ filter: /^\.\/Render-[A-Za-z0-9]+\.mjs$/ }, (args) =>
      args.importer.includes(`${path.sep}@puckeditor${path.sep}core${path.sep}`) ? { path: args.path, namespace: "puck-richtext" } : undefined,
    );
    pluginBuild.onLoad({ filter: /.*/, namespace: "puck-richtext" }, () => ({
      contents: 'export function RichTextRender() { throw new Error("a richtext field cannot be drawn on a live page"); }',
      loader: "js",
    }));
  },
};
// Agent sections get zod's whole namespace (src/section-host.ts), and `z.locales` on it would bring
// zod's 53 translations of its error messages (~190 KB). A published page never validates props,
// and zod speaks English unless told otherwise, so the runtime's zod knows English alone.
const zodEnglishOnly = {
  name: "zod-english-only",
  setup(pluginBuild) {
    pluginBuild.onResolve({ filter: /^\.\.\/locales\/index\.js$/ }, (args) =>
      args.importer.includes(`${path.sep}zod${path.sep}v4${path.sep}`)
        ? { path: path.join(path.dirname(args.importer), "..", "locales", "en.js"), namespace: "zod-locales" }
        : undefined,
    );
    pluginBuild.onLoad({ filter: /.*/, namespace: "zod-locales" }, (args) => ({
      contents: `export { default as en } from ${JSON.stringify(args.path)};`,
      resolveDir: path.dirname(args.path),
      loader: "js",
    }));
  },
};
const runtime = await build({
  absWorkingDir: root,
  entryPoints: ["src/site-runtime.tsx"],
  outfile: path.join(dist, "site-runtime.js"),
  bundle: true,
  platform: "browser",
  format: "esm",
  target: "chrome120",
  jsx: "automatic",
  minify: true,
  legalComments: "none",
  define: { "process.env.NODE_ENV": '"production"' },
  logLevel: "warning",
  banner,
  metafile: true,
  plugins: [withoutPuckRichText, zodEnglishOnly],
});
// Every visitor of a live page downloads this file, so the build reports what is inside it (bytes per
// package) to dist/site-runtime.packages.json; test/bundles.test.ts keeps editor code out of it.
await fs.writeFile(path.join(dist, "site-runtime.packages.json"), JSON.stringify(runtimePackages(runtime.metafile), null, 1));

// The shims re-export every name the runtime's own copies have (src/section-host.ts). This script
// runs with plain node, which cannot import .ts, so section-host is bundled for node into a temp
// file first and imported from there.
const temp = await fs.mkdtemp(path.join(os.tmpdir(), "site-kit-shims-"));
try {
  const sectionHost = path.join(temp, "section-host.mjs");
  await build({
    absWorkingDir: root,
    entryPoints: ["src/section-host.ts"],
    outfile: sectionHost,
    bundle: true,
    platform: "node",
    format: "esm",
    target: "node22",
    define: { "process.env.NODE_ENV": '"production"' },
    logLevel: "warning",
  });
  const host = await import(pathToFileURL(sectionHost).href);
  const modules = host.hostModules();
  const shims = path.join(dist, "site-runtime-shims");
  await fs.mkdir(shims, { recursive: true });
  const SHIM_FILES = { react: "react.js", "react/jsx-runtime": "react-jsx-runtime.js", zod: "zod.js" };
  for (const specifier of host.HOST_SPECIFIERS) {
    await fs.writeFile(path.join(shims, SHIM_FILES[specifier]), host.shimSource(specifier, host.hostExportNames(modules[specifier])));
  }
} finally {
  await fs.rm(temp, { recursive: true, force: true });
}
console.error(`site-kit bundles written to ${dist}`);

function runtimePackages(metafile) {
  const output = Object.values(metafile.outputs).find((entry) => entry.entryPoint === "src/site-runtime.tsx");
  const packages = {};
  for (const [file, input] of Object.entries(output.inputs)) {
    const name = file.match(/node_modules\/((?:@[^/]+\/)?[^/]+)/)?.[1] ?? "site-kit";
    packages[name] = (packages[name] ?? 0) + input.bytesInOutput;
  }
  return { bytes: output.bytes, packages: Object.fromEntries(Object.entries(packages).sort((a, b) => b[1] - a[1])) };
}
