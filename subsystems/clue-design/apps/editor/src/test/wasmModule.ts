import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import type { WasmModule } from "@/engine/wasmEngine";

/**
 * Test-side loader for the real wasm-pack artifact in `public/wasm/`.
 * Vitest runs on Node, which instantiates the same module the browser
 * loads — so suites exercise the actual engine, not a mock. Suites must
 * skip (with a notice) when the artifact has not been built; the
 * conformance gate builds it first via `npm run build:wasm`.
 */

const wasmDir = path.resolve(__dirname, "../../public/wasm");
const jsPath = path.join(wasmDir, "lumen_wasm.js");
const wasmPath = path.join(wasmDir, "lumen_wasm_bg.wasm");

export const wasmArtifactPresent = existsSync(jsPath) && existsSync(wasmPath);

let modulePromise: Promise<WasmModule> | null = null;

export function loadWasmModuleFromDisk(): Promise<WasmModule> {
  modulePromise ??= initializeModule();
  return modulePromise;
}

async function initializeModule(): Promise<WasmModule> {
  if (!wasmArtifactPresent) {
    throw new Error(
      `wasm artifact missing at ${wasmDir}; run \`npm run build:wasm\` before the wasm suites`
    );
  }
  const module = (await import(/* @vite-ignore */ pathToFileURL(jsPath).href)) as WasmModule & {
    initSync: (input: unknown) => unknown;
  };
  const bytes = readFileSync(wasmPath);
  try {
    module.initSync({ module: bytes });
  } catch {
    // Older wasm-bindgen initSync signatures take the bytes directly.
    module.initSync(bytes);
  }
  return module;
}
