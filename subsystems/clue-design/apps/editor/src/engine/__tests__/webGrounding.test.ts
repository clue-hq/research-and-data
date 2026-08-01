import { describe, expect, it } from "vitest";

import { parseWebGroundingSummary } from "@/engine/webGrounding";

describe("parseWebGroundingSummary", () => {
  it("projects fetched pages and library assets without raw page text", () => {
    const summary = parseWebGroundingSummary({
      schema_version: 1,
      sources: [
        {
          source_id: "page_123",
          kind: "page",
          title: "Acme facts",
          final_url: "https://acme.test/about",
          text: "large raw fetched content"
        },
        {
          source_id: "asset_456",
          kind: "asset",
          asset_id: "asset_logo",
          label: "Acme logo"
        }
      ],
      citations: [{ citation_id: "citation_1" }]
    });

    expect(summary).toEqual({
      sources: [
        {
          sourceId: "page_123",
          kind: "page",
          label: "Acme facts",
          url: "https://acme.test/about",
          assetId: null
        },
        {
          sourceId: "asset_456",
          kind: "asset",
          label: "Acme logo",
          url: null,
          assetId: "asset_logo"
        }
      ],
      citationCount: 1
    });
    expect(JSON.stringify(summary)).not.toContain("large raw fetched content");
  });

  it("ignores malformed sources and returns null for an empty report", () => {
    expect(
      parseWebGroundingSummary({
        sources: [{ kind: "page", final_url: "https://acme.test" }],
        citations: []
      })
    ).toBeNull();
    expect(parseWebGroundingSummary(null)).toBeNull();
  });
});
