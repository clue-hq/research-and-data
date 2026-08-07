import { afterEach, describe, expect, it, vi } from "vitest";
import { canvasKitFlagEnabled, wasmCoreFlagEnabled } from "../wasmEngine";

/**
 * The engine flags are OPT-OUT: a plain `npm run dev` (no env vars) must get a
 * fully working editor — WASM core active, CanvasKit rendering. The core flag
 * regressing to opt-in ships a rendered-but-uneditable canvas to anyone who
 * starts the frontend outside `dev-setup.sh frontend`.
 */
describe("engine feature flags", () => {
  const savedCore = process.env.NEXT_PUBLIC_LUMEN_WASM_CORE;

  afterEach(() => {
    vi.unstubAllEnvs();
    if (savedCore === undefined) {
      delete process.env.NEXT_PUBLIC_LUMEN_WASM_CORE;
    } else {
      process.env.NEXT_PUBLIC_LUMEN_WASM_CORE = savedCore;
    }
  });

  it("enables the WASM core by default (unset env)", () => {
    delete process.env.NEXT_PUBLIC_LUMEN_WASM_CORE;
    expect(wasmCoreFlagEnabled()).toBe(true);
  });

  it("keeps explicit opt-in and opt-out working for the WASM core", () => {
    vi.stubEnv("NEXT_PUBLIC_LUMEN_WASM_CORE", "1");
    expect(wasmCoreFlagEnabled()).toBe(true);
    vi.stubEnv("NEXT_PUBLIC_LUMEN_WASM_CORE", "0");
    expect(wasmCoreFlagEnabled()).toBe(false);
    vi.stubEnv("NEXT_PUBLIC_LUMEN_WASM_CORE", "false");
    expect(wasmCoreFlagEnabled()).toBe(false);
  });

  it("keeps CanvasKit opt-out semantics unchanged", () => {
    vi.stubEnv("NEXT_PUBLIC_LUMEN_CANVASKIT", "0");
    expect(canvasKitFlagEnabled()).toBe(false);
    vi.stubEnv("NEXT_PUBLIC_LUMEN_CANVASKIT", "1");
    expect(canvasKitFlagEnabled()).toBe(true);
  });
});
