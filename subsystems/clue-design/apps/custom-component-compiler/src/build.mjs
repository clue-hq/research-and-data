import path from "node:path";
import vm from "node:vm";

import esbuild from "esbuild";
import postcss from "postcss";
import tailwindcss from "tailwindcss";

import {
  ALLOWED_BARE_IMPORTS,
  MAX_FIRST_FRAME_BYTES,
  RENDER_TIMEOUT_MS,
  diagnostic,
} from "./contracts.mjs";
import {
  resolveComponentRelative,
  resolvePackage,
} from "./analyze.mjs";

const COMPONENT_NAMESPACE = "lumen-component";
const ENTRY_NAMESPACE = "lumen-entry";
const DEPENDENCY_NAMESPACE = "lumen-dependency";

function loaderFor(file) {
  const extension = path.posix.extname(file);
  if (extension === ".tsx") return "tsx";
  if (extension === ".ts") return "ts";
  if (extension === ".jsx") return "jsx";
  return "js";
}

function componentPlugin(input, mode) {
  const browser = mode === "browser";
  return {
    name: "lumen-custom-component-files",
    setup(build) {
      build.onResolve({ filter: /^lumen:entry$/ }, () => ({
        path: "entry",
        namespace: ENTRY_NAMESPACE,
      }));
      build.onLoad({ filter: /.*/, namespace: ENTRY_NAMESPACE }, () => {
        if (browser) {
          return {
            contents: `export { default } from ${JSON.stringify(`./${input.entry}`)};`,
            loader: "js",
            resolveDir: "/component",
          };
        }
        return {
          contents: `
            import React from "react";
            import { renderToStaticMarkup } from "react-dom/server.browser";
            import Component from ${JSON.stringify(`./${input.entry}`)};
            const theme = {
              colors: { primary: "#335cff", secondary: "#7c3aed", dark: "#111827", light: "#ffffff" },
              fonts: { body: "system-ui", heading: "system-ui" },
              shadows: {},
              breakpoints: { sm: "640px", md: "768px", lg: "1024px", xl: "1280px" }
            };
            export function render() {
              return renderToStaticMarkup(
                React.createElement(Component, { props: {}, theme, overrideVariables: {} })
              );
            }
          `,
          loader: "js",
          resolveDir: "/component",
        };
      });

      build.onResolve(
        { filter: /.*/, namespace: ENTRY_NAMESPACE },
        (args) => resolveFromVirtual(args, input, browser),
      );
      build.onResolve(
        { filter: /.*/, namespace: COMPONENT_NAMESPACE },
        (args) => resolveFromVirtual(args, input, browser),
      );
      build.onResolve(
        { filter: /.*/, namespace: DEPENDENCY_NAMESPACE },
        (args) => resolveFromVirtual(args, input, browser),
      );

      build.onLoad(
        { filter: /.*/, namespace: COMPONENT_NAMESPACE },
        (args) => ({
          contents: input.files[args.path],
          loader: loaderFor(args.path),
          resolveDir: path.posix.join("/component", path.posix.dirname(args.path)),
        }),
      );
      build.onLoad(
        { filter: /.*/, namespace: DEPENDENCY_NAMESPACE },
        (args) => ({
          contents: `
            import React from "react";
            export default function PinnedComponentDependency() {
              return React.createElement("div", {
                "data-custom-component-dependency": ${JSON.stringify(args.path)},
                "data-artifact-id": ${JSON.stringify(input.component_artifacts[args.path])}
              });
            }
          `,
          loader: "js",
          resolveDir: "/component",
        }),
      );
    },
  };
}

function resolveFromVirtual(args, input, browser) {
  const specifier = args.path;
  if (specifier.startsWith(".")) {
    const importer =
      args.namespace === ENTRY_NAMESPACE || args.namespace === DEPENDENCY_NAMESPACE
        ? input.entry
        : args.importer;
    const resolved = resolveComponentRelative(importer, specifier, input.files);
    if (!resolved.path) {
      return {
        errors: [{ text: `relative import does not resolve: ${specifier}` }],
      };
    }
    return { path: resolved.path, namespace: COMPONENT_NAMESPACE };
  }
  if (specifier.startsWith("components/")) {
    const dependency = specifier.slice("components/".length);
    return browser
      ? { path: specifier, external: true }
      : { path: dependency, namespace: DEPENDENCY_NAMESPACE };
  }
  if (
    ALLOWED_BARE_IMPORTS.has(specifier) ||
    specifier === "react-dom/server.browser"
  ) {
    if (
      browser &&
      (specifier === "react" ||
        specifier === "react/jsx-runtime" ||
        specifier === "react/jsx-dev-runtime")
    ) {
      return { path: specifier, external: true };
    }
    return { path: resolvePackage(specifier) };
  }
  return { errors: [{ text: `bare import is not allowed: ${specifier}` }] };
}

function esbuildDiagnostics(error, category) {
  const errors = error?.errors ?? [];
  if (!errors.length) {
    return [
      diagnostic({
        code: category === "render" ? "CCC0501" : "CCC0401",
        category,
        message: error instanceof Error ? error.message : String(error),
      }),
    ];
  }
  return errors.map((item) =>
    diagnostic({
      code: category === "render" ? "CCC0501" : "CCC0401",
      category,
      message: item.text,
      file: item.location?.file || null,
      line: item.location?.line || null,
      column: item.location?.column || null,
    }),
  );
}

export async function buildBrowserBundle(input) {
  try {
    const result = await esbuild.build({
      entryPoints: ["lumen:entry"],
      bundle: true,
      charset: "utf8",
      define: { "process.env.NODE_ENV": '"production"' },
      external: ["react", "react/jsx-runtime", "react/jsx-dev-runtime"],
      format: "esm",
      jsx: "automatic",
      legalComments: "none",
      minify: true,
      platform: "browser",
      plugins: [componentPlugin(input, "browser")],
      sourcemap: false,
      target: ["es2020"],
      treeShaking: true,
      write: false,
    });
    return { bundle: result.outputFiles[0].text, diagnostics: [] };
  } catch (error) {
    return { bundle: null, diagnostics: esbuildDiagnostics(error, "build") };
  }
}

export async function buildComponentCss(input) {
  try {
    const rawSource = Object.entries(input.files)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([file, source]) => `/* ${file} */\n${source}`)
      .join("\n");
    const result = await postcss([
      tailwindcss({
        content: [{ raw: rawSource, extension: "tsx" }],
        corePlugins: { preflight: false },
        theme: {
          extend: {
            colors: {
              primary: "var(--lumen-color-primary)",
              secondary: "var(--lumen-color-secondary)",
              dark: "var(--lumen-color-dark)",
              light: "var(--lumen-color-light)",
            },
            fontFamily: {
              body: "var(--lumen-font-body)",
              heading: "var(--lumen-font-heading)",
            },
          },
        },
      }),
    ]).process("@tailwind components;\n@tailwind utilities;\n", { from: undefined });
    return {
      css: `/* lumen custom component css v1 */\n${result.css.trim()}\n`,
      diagnostics: [],
    };
  } catch (error) {
    return {
      css: null,
      diagnostics: [
        diagnostic({
          code: "CCC0601",
          category: "tailwind",
          message: error instanceof Error ? error.message : String(error),
        }),
      ],
    };
  }
}

export async function renderFirstFrame(input) {
  let bundle;
  try {
    const result = await esbuild.build({
      entryPoints: ["lumen:entry"],
      bundle: true,
      charset: "utf8",
      define: { "process.env.NODE_ENV": '"production"' },
      format: "iife",
      globalName: "__lumenSSR",
      jsx: "automatic",
      legalComments: "none",
      minify: true,
      platform: "node",
      plugins: [componentPlugin(input, "ssr")],
      sourcemap: false,
      target: ["node20"],
      treeShaking: true,
      write: false,
    });
    bundle = result.outputFiles[0].text;
  } catch (error) {
    return { html: null, diagnostics: esbuildDiagnostics(error, "render") };
  }

  try {
    const context = vm.createContext(
      {
        __lumenResult: null,
        console: Object.freeze({
          log() {},
          warn() {},
          error() {},
        }),
        TextDecoder,
        TextEncoder,
      },
      {
        codeGeneration: { strings: false, wasm: false },
        name: "lumen-custom-component-ssr",
      },
    );
    vm.runInContext(
      `
        globalThis.queueMicrotask = (callback) => callback();
        globalThis.Date = class DeterministicDate extends Date {
          constructor(...args) { super(...(args.length ? args : [0])); }
          static now() { return 0; }
        };
        globalThis.Math.random = () => 0.5;
      `,
      context,
      { timeout: RENDER_TIMEOUT_MS },
    );
    vm.runInContext(bundle, context, { timeout: RENDER_TIMEOUT_MS });
    vm.runInContext("__lumenResult = __lumenSSR.render()", context, {
      timeout: RENDER_TIMEOUT_MS,
    });
    const html = context.__lumenResult;
    if (typeof html !== "string" || html.length === 0) {
      throw new Error("first-frame render produced no markup");
    }
    if (Buffer.byteLength(html, "utf8") > MAX_FIRST_FRAME_BYTES) {
      throw new Error(
        `first-frame render exceeds ${MAX_FIRST_FRAME_BYTES} bytes`,
      );
    }
    return { html, diagnostics: [] };
  } catch (error) {
    return {
      html: null,
      diagnostics: [
        diagnostic({
          code: "CCC0502",
          category: "render",
          message: `first-frame render failed: ${
            error instanceof Error ? error.message : String(error)
          }`,
        }),
      ],
    };
  }
}
