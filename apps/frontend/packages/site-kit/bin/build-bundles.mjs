// Builds the site kit's runnable files into dist/, each one file with its dependencies inside,
// so the design API and the fleet workers run them with plain `node` (their image has no
// apps/frontend/node_modules):
//   dist/validate-site.mjs   the validator CLI (bin/validate-site.ts)
//   dist/build-catalog.mjs   the catalog CLI (bin/build-catalog.ts)
// Usage: node bin/build-bundles.mjs   (npm run build -w @clue/site-kit)
import path from "node:path";
import { fileURLToPath } from "node:url";
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
console.error(`site-kit bundles written to ${dist}`);
