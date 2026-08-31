import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import type { WasmModule } from "../wasmEngine";

/**
 * Test-side loader for the real wasm-pack artifact in `public/vendor/wasm/`.
 * The suites run on Node, which instantiates the same module the browser
 * loads — so they exercise the actual engine, not a mock. Suites must
 * skip (with a notice) when the artifact has not been vendored; the
 * frontend's `scripts/copy-design-vendor.mjs` puts it there.
 *
 * Ported at AD1.6 from `subsystems/clue-design/apps/editor/src/test/wasmModule.ts`.
 * Three adaptations, all forced by this repo's CommonJS test runtime:
 *  1. the directory is the frontend's vendored `public/vendor/wasm`
 *     (upstream: `public/wasm`);
 *  2. the artifact's ESM entry is reached through a runtime-constructed
 *     dynamic import — `tsx --test` transpiles this file to CommonJS, where a
 *     literal `await import(...)` is lowered to `require()`;
 *  3. the loaded namespace is unwrapped. `apps/frontend/package.json` declares
 *     no `"type": "module"`, so `lumen_wasm.js` sits in a CJS scope and tsx
 *     hands back the wasm-pack exports under `default` rather than as named
 *     exports. `moduleNamespace` accepts either shape.
 */

const wasmDir = path.resolve(__dirname, "../../../../../../public/vendor/wasm");
const jsPath = path.join(wasmDir, "lumen_wasm.js");
const wasmPath = path.join(wasmDir, "lumen_wasm_bg.wasm");

export const wasmArtifactPresent = existsSync(jsPath) && existsSync(wasmPath);

/** True ESM `import()`, opaque to the CJS transpile (see the note above). */
const importEsm = new Function("specifier", "return import(specifier);") as (
  specifier: string,
) => Promise<unknown>;

type InitableWasmModule = WasmModule & { initSync: (input: unknown) => unknown };

/** Named exports when the artifact loads as ESM; the `default` interop object
 * when it is transpiled into this package's CommonJS scope (see note 3). */
function moduleNamespace(loaded: unknown): InitableWasmModule {
  const namespace = loaded as Partial<InitableWasmModule> & { default?: unknown };
  if (typeof namespace.initSync === "function") {
    return namespace as InitableWasmModule;
  }
  const inner = namespace.default as Partial<InitableWasmModule> | undefined;
  if (inner && typeof inner.initSync === "function") {
    return inner as InitableWasmModule;
  }
  throw new Error(`wasm artifact at ${jsPath} exposes no initSync entry point`);
}

let modulePromise: Promise<WasmModule> | null = null;

export function loadWasmModuleFromDisk(): Promise<WasmModule> {
  modulePromise ??= initializeModule();
  return modulePromise;
}

async function initializeModule(): Promise<WasmModule> {
  if (!wasmArtifactPresent) {
    throw new Error(
      `wasm artifact missing at ${wasmDir}; run \`node scripts/copy-design-vendor.mjs\` before the wasm suites`,
    );
  }
  const module = moduleNamespace(await importEsm(pathToFileURL(jsPath).href));
  const bytes = readFileSync(wasmPath);
  try {
    module.initSync({ module: bytes });
  } catch {
    // Older wasm-bindgen initSync signatures take the bytes directly.
    module.initSync(bytes);
  }
  return module;
}
