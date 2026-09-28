import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    files: [
      "src/components/**/*.tsx",
      "src/features/**/components/**/*.tsx",
    ],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: [
                "**/data/**",
                "**/*.fixture",
                "**/*.repository",
              ],
              message:
                "Presentation components must receive typed props and must not import repositories or fixtures.",
            },
          ],
        },
      ],
    },
  },
  {
    files: ["src/app/**/*.tsx"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["**/*.fixture"],
              message:
                "Routes must use repositories; fixture selection belongs inside data adapters.",
            },
          ],
        },
      ],
    },
  },
  {
    // `wasmEngine.ts` is a verbatim port of the design subsystem's engine
    // module (AD1.5). Its wasm loader binds the loaded wasm-pack namespace to
    // a function-scoped `const module` — the Next rule fires on the NAME, but
    // this is never the CommonJS `module` global (the file is ESM-only and the
    // binding is block-scoped), so the warning does not apply here. Scoped to
    // the one file so the rule keeps protecting everything else.
    files: [
      "src/features/design-editor/engine/scene/wasmEngine.ts",
      // Same rule, same reason, for the AD1.6 wasm suites: `const module =
      // await loadWasmModuleFromDisk()` is the upstream text of every ported
      // artifact case, and the loader binds the loaded wasm-pack namespace
      // the same way. All are function-scoped consts in ESM sources.
      "src/features/design-editor/engine/scene/__tests__/wasm-module-loader.ts",
      "src/features/design-editor/engine/scene/__tests__/wasm-artifact.test.ts",
      "src/features/design-editor/engine/scene/__tests__/wasmEngine.artifact.test.ts",
      "src/features/design-editor/engine/scene/__tests__/wasmHandshake.test.ts",
      "src/features/design-editor/engine/scene/__tests__/wasmTextSpans.artifact.test.ts",
    ],
    rules: {
      "@next/next/no-assign-module-variable": "off",
    },
  },
  {
    // The vitest shim's `vi.mock` swaps a CommonJS `require.cache` entry — the
    // only module-mocking mechanism available under `tsx --test`, which
    // transpiles this package's sources to CJS (see the shim's `vi.mock` doc).
    // Its two consumers must likewise pull the module under test in with a
    // body-level `require()` so the swap lands first. These are deliberate
    // CommonJS reaches inside test-only code, not stray import style.
    files: [
      "src/features/design-editor/engine/__tests__/vitest-shim.ts",
      "src/features/design-editor/engine/scene/__tests__/kitFonts.test.ts",
      "src/features/design-editor/engine/scene/__tests__/libraryFonts.test.ts",
    ],
    rules: {
      "@typescript-eslint/no-require-imports": "off",
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    ".next-local-*/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Generated vendor assets (scripts/copy-design-vendor.mjs) — third-party
    // minified bundles, not lintable source.
    "public/vendor/**",
  ]),
]);

export default eslintConfig;
