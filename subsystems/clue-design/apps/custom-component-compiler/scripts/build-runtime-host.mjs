import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import esbuild from "esbuild";

const compilerRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const outputPath = path.resolve(
  compilerRoot,
  "..",
  "api",
  "lumen_api",
  "runtime_assets",
  "custom-component-react-host-v1.js",
);

const result = await esbuild.build({
  stdin: {
    contents: `
      import React from "react";
      import * as ReactJsxRuntime from "react/jsx-runtime";
      import * as ReactJsxDevRuntime from "react/jsx-dev-runtime";
      import { createRoot, hydrateRoot } from "react-dom/client";
      Object.defineProperties(globalThis, {
        __LumenReact: { value: React, configurable: false, writable: false },
        __LumenReactJsxRuntime: {
          value: ReactJsxRuntime,
          configurable: false,
          writable: false
        },
        __LumenReactJsxDevRuntime: {
          value: ReactJsxDevRuntime,
          configurable: false,
          writable: false
        },
        __LumenReactDOMClient: {
          value: Object.freeze({ createRoot, hydrateRoot }),
          configurable: false,
          writable: false
        }
      });
    `,
    resolveDir: compilerRoot,
    sourcefile: "lumen-custom-component-react-host-v1.js",
  },
  bundle: true,
  charset: "utf8",
  define: { "process.env.NODE_ENV": '"production"' },
  format: "iife",
  legalComments: "none",
  minify: true,
  platform: "browser",
  sourcemap: false,
  target: ["es2020"],
  treeShaking: true,
  write: false,
});

const output = `/* lumen custom component React host v1; generated, do not edit */\n${result.outputFiles[0].text}`;
if (process.argv.includes("--check")) {
  let current = null;
  try {
    current = await fs.readFile(outputPath, "utf8");
  } catch {
    // The comparison below owns the failure.
  }
  if (current !== output) {
    throw new Error(
      "custom-component React host is stale; run npm run build:runtime-host",
    );
  }
  console.log("custom-component React host is current");
} else {
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await fs.writeFile(outputPath, output, "utf8");
  console.log(path.relative(compilerRoot, outputPath));
}
