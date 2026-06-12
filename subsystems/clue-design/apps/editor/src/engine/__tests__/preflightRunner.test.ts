import { describe, expect, it } from "vitest";
import { preflightResultFromUnknown } from "../preflightRunner";

describe("preflight runner", () => {
  it("normalizes compact preflight-preview payloads", () => {
    const result = preflightResultFromUnknown({
      status: "applied",
      scene: {
        schema_version: 1,
        pages: {},
        nodes: {},
        slots: {},
        assets: {},
        export_profiles: [],
        meta: {
          id: "doc",
          title: "Doc",
          status: {
            kind: "draft"
          }
        }
      },
      diagnostics: [
        {
          severity: "warning",
          phase: "layout",
          code: "LAYOUT_TEXT_FIT",
          message: "Text may overflow",
          subject: {
            kind: "node",
            id: "node_headline"
          },
          hint: "Reduce copy length."
        }
      ],
      preflight: {
        has_errors: false,
        brand_ref_operations: 1,
        token_operations: 2,
        layout_operations: 3
      },
      brand_kit: {
        source: "platform_default",
        id: "brand_kit_platform_default",
        version: 1,
        name: "Platform Default"
      }
    });

    expect(result.status).toBe("applied");
    expect(result.scene?.meta.title).toBe("Doc");
    expect(result.preflight.layout_operations).toBe(3);
    expect(result.brand_kit.source).toBe("platform_default");
    expect(result.diagnostics).toEqual([
      {
        severity: "warning",
        phase: "layout",
        code: "LAYOUT_TEXT_FIT",
        message: "Text may overflow",
        subject: {
          kind: "node",
          id: "node_headline"
        },
        hint: "Reduce copy length."
      }
    ]);
  });

  it("fails closed on malformed payloads", () => {
    const result = preflightResultFromUnknown(null);

    expect(result.status).toBe("failed");
    expect(result.scene).toBeNull();
    expect(result.diagnostics[0]).toMatchObject({
      severity: "error",
      phase: "validation",
      code: "EDITOR_PREFLIGHT_INVALID_RESPONSE"
    });
  });
});
