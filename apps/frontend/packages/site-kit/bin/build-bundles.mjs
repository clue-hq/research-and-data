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
await build({
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
});

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
