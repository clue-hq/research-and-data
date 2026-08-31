// @vitest-environment node
import { describe, expect, it, vi } from "../../__tests__/vitest-shim";

import { activateWasmCore, type WasmModule } from "../wasmEngine";
import { loadWasmModuleFromDisk, wasmArtifactPresent } from "./wasm-module-loader";

/**
 * Track E W5: the version handshake. The module's
 * { schema_version, engine_commit } must equal the API's /build-info
 * exactly or the editor stays in server-only mode. An unverifiable
 * version (API unreachable, malformed payload) counts as a mismatch —
 * never mixed-version optimistic editing.
 */

/**
 * Ported at AD1.6. The ONE adaptation: `activateWasmCore` no longer defaults
 * its API origin from ambient env (AD1.5 made `apiBaseUrl` a required option
 * and deleted the flag readers), so every call site below passes an explicit
 * base. The mocked transports ignore the URL, so no assertion changes — the
 * handshake semantics under test are identical. No case exercised the deleted
 * flag functions, so nothing was dropped: all 7 upstream cases are here.
 */
const API_BASE_URL = "http://api.test";

function fetchReturning(payload: unknown, status = 200): typeof fetch {
  return vi.fn(async () => ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload
  })) as unknown as typeof fetch;
}

describe("activateWasmCore handshake", () => {
  it("reports load_failed when the module cannot be loaded", async () => {
    const activation = await activateWasmCore({
      apiBaseUrl: API_BASE_URL,
      moduleLoader: async () => null,
      fetchImpl: fetchReturning({})
    });
    expect(activation.status).toBe("unavailable");
    if (activation.status === "unavailable") {
      expect(activation.reason).toBe("load_failed");
    }
  });

  describe.skipIf(!wasmArtifactPresent)("with the real module", () => {
    async function realModule(): Promise<WasmModule> {
      return loadWasmModuleFromDisk();
    }

    it("activates when the API reports the identical engine build", async () => {
      const module = await realModule();
      const version = JSON.parse(module.engineVersion()) as {
        schema_version: number;
        engine_commit: string;
      };
      const activation = await activateWasmCore({
        apiBaseUrl: API_BASE_URL,
        moduleLoader: async () => module,
        fetchImpl: fetchReturning({
          schema_version: 1,
          build_info: {
            schema_version: version.schema_version,
            engine_commit: version.engine_commit
          }
        })
      });
      expect(activation.status).toBe("active");
    });

    it("downgrades on engine commit mismatch", async () => {
      const module = await realModule();
      const version = JSON.parse(module.engineVersion()) as { schema_version: number };
      const activation = await activateWasmCore({
        apiBaseUrl: API_BASE_URL,
        moduleLoader: async () => module,
        fetchImpl: fetchReturning({
          schema_version: 1,
          build_info: {
            schema_version: version.schema_version,
            engine_commit: "deadbeef0000"
          }
        })
      });
      expect(activation.status).toBe("unavailable");
      if (activation.status === "unavailable") {
        expect(activation.reason).toBe("version_mismatch");
        expect(activation.detail).toContain("deadbeef0000");
      }
    });

    it("downgrades on schema version mismatch", async () => {
      const module = await realModule();
      const version = JSON.parse(module.engineVersion()) as { engine_commit: string };
      const activation = await activateWasmCore({
        apiBaseUrl: API_BASE_URL,
        moduleLoader: async () => module,
        fetchImpl: fetchReturning({
          schema_version: 1,
          build_info: {
            schema_version: 999,
            engine_commit: version.engine_commit
          }
        })
      });
      expect(activation.status).toBe("unavailable");
      if (activation.status === "unavailable") {
        expect(activation.reason).toBe("version_mismatch");
      }
    });

    it("downgrades when the API build info is unreachable", async () => {
      const module = await realModule();
      const failingFetch = vi.fn(async () => {
        throw new Error("api offline");
      }) as unknown as typeof fetch;
      const activation = await activateWasmCore({
        apiBaseUrl: API_BASE_URL,
        moduleLoader: async () => module,
        fetchImpl: failingFetch
      });
      expect(activation.status).toBe("unavailable");
      if (activation.status === "unavailable") {
        expect(activation.reason).toBe("handshake_failed");
        expect(activation.detail).toContain("api offline");
      }
    });

    it("downgrades on non-200 build-info responses", async () => {
      const module = await realModule();
      const activation = await activateWasmCore({
        apiBaseUrl: API_BASE_URL,
        moduleLoader: async () => module,
        fetchImpl: fetchReturning({}, 500)
      });
      expect(activation.status).toBe("unavailable");
      if (activation.status === "unavailable") {
        expect(activation.reason).toBe("handshake_failed");
      }
    });

    it("treats a missing build_info payload as a mismatch", async () => {
      const module = await realModule();
      const activation = await activateWasmCore({
        apiBaseUrl: API_BASE_URL,
        moduleLoader: async () => module,
        fetchImpl: fetchReturning({ schema_version: 1 })
      });
      expect(activation.status).toBe("unavailable");
      if (activation.status === "unavailable") {
        expect(activation.reason).toBe("version_mismatch");
      }
    });
  });
});
