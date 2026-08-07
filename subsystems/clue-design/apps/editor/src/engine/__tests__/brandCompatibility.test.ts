import { afterEach, describe, expect, it, vi } from "vitest";
import { minimalScene } from "@/fixtures/minimalScene";
import { createApiBrandCompatibilityRunner } from "../brandCompatibility";

describe("brandCompatibility", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts Brand Kit compatibility requests and normalizes report payloads", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        status: "failed",
        report: {
          from: {
            id: "brand_kit_insight_health",
            version: 4
          },
          to: {
            id: "brand_kit_insight_health",
            version: 5
          },
          status: "migration_required",
          diagnostics: [
            {
              severity: "error",
              code: "LUMB0814",
              message: "color token surface.brand was removed",
              subject: {
                kind: "document"
              },
              hint: "Choose a replacement token."
            }
          ],
          token_changes: [
            {
              path: "surface.brand",
              kind: "removed",
              from_kind: "color",
              to_kind: null
            }
          ]
        },
        diagnostics: [
          {
            severity: "error",
            code: "LUMB0814",
            message: "color token surface.brand was removed",
            subject: {
              kind: "document"
            },
            hint: "Choose a replacement token."
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

    const runner = createApiBrandCompatibilityRunner({
      apiBaseUrl: "https://api.example.test",
      toRef: {
        id: "brand_kit_insight_health",
        version: 5
      },
      persistReport: false
    });
    const result = await runner({
      scene,
      currentBrandKit: null,
      targetBrandKit: null
    });

    expect(fetchMock).toHaveBeenCalledWith(
      new URL("https://api.example.test/brand-kits/compatibility"),
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          from_ref: {
            brand_kit_id: "brand_kit_insight_health",
            version: 4
          },
          to_ref: {
            brand_kit_id: "brand_kit_insight_health",
            version: 5
          },
          persist_report: false
        })
      })
    );
    expect(result.status).toBe("failed");
    expect(result.report).toEqual(
      expect.objectContaining({
        status: "migration_required",
        token_changes: [
          {
            path: "surface.brand",
            kind: "removed",
            from_kind: "color",
            to_kind: null
          }
        ]
      })
    );
    expect(result.diagnostics).toEqual([
      {
        severity: "error",
        phase: "brand",
        code: "LUMB0814",
        message: "color token surface.brand was removed",
        subject: {
          kind: "document"
        },
        hint: "Choose a replacement token."
      }
    ]);
  });
});
