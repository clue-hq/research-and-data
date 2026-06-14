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

  it("normalizes grouped preflight-preview diagnostics from the API", () => {
    const result = preflightResultFromUnknown({
      status: "failed",
      diagnostics: {
        audit: [
          {
            severity: "advice",
            phase: "validation",
            code: "LUMV0805",
            message: "page page_a4 uses legacy non-pt geometry unit Mm"
          }
        ],
        current: [
          {
            severity: "error",
            phase: "layout",
            code: "LUMV0812",
            message: "slot contact.full_name fixture does not fit even at min font size 12",
            subject: {
              kind: "slot",
              id: "slot_contact_name"
            }
          }
        ]
      },
      preflight: {
        has_errors: true,
        brand_ref_operations: 0,
        token_operations: 0,
        layout_operations: 1
      }
    });

    expect(result.status).toBe("failed");
    expect(result.preflight.has_errors).toBe(true);
    expect(result.diagnostics).toEqual([
      {
        severity: "error",
        phase: "layout",
        code: "LUMV0812",
        message: "slot contact.full_name fixture does not fit even at min font size 12",
        subject: {
          kind: "slot",
          id: "slot_contact_name"
        },
        hint: null
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
