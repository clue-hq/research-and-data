import { afterEach, describe, expect, it, vi } from "vitest";
import { minimalScene } from "@/fixtures/minimalScene";
import { createApiBrandGovernanceRunner } from "../brandGovernance";

describe("brandGovernance", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts document Brand Kit governance requests and normalizes diagnostics", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        status: "failed",
        diagnostics: [
          {
            severity: "error",
            phase: "brand",
            code: "LUMB0810",
            message: "node logo is on a disallowed background",
            subject: {
              kind: "node",
              id: "node_logo"
            },
            hint: "Use an allowed Brand Kit surface."
          }
        ]
      })
    });
    vi.stubGlobal("fetch", fetchMock);

    const scene = structuredClone(minimalScene);
    scene.meta.brand_kit = {
      id: "brand_kit_insight_health",
      version: 4
    };

    const runner = createApiBrandGovernanceRunner({
      apiBaseUrl: "https://api.example.test",
      strictness: "finalize"
    });
    const result = await runner({ scene, brandKit: null });

    expect(fetchMock).toHaveBeenCalledWith(
      new URL("https://api.example.test/documents/doc_demo/brand-governance"),
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          brand_kit_id: "brand_kit_insight_health",
          version: 4,
          strictness: "finalize"
        })
      })
    );
    expect(result.status).toBe("failed");
    expect(result.diagnostics).toEqual([
      {
        severity: "error",
        phase: "brand",
        code: "LUMB0810",
        message: "node logo is on a disallowed background",
        subject: {
          kind: "node",
          id: "node_logo"
        },
        hint: "Use an allowed Brand Kit surface."
      }
    ]);
  });
});
