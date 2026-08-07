/** Presentation-safe projection of the website-agent grounding envelope.
 *
 * The API persists richer source records (including fetched text and exact
 * provenance). The editor transcript only needs stable labels/links/counts,
 * so this parser rejects malformed entries and never renders raw page text.
 */

export interface WebGroundingSourceSummary {
  sourceId: string;
  kind: "page" | "asset";
  label: string;
  url: string | null;
  assetId: string | null;
}

export interface WebGroundingSummary {
  sources: WebGroundingSourceSummary[];
  citationCount: number;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function nonEmptyString(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : null;
}

/** Parse the durable API envelope into the compact evidence card shown in chat. */
export function parseWebGroundingSummary(value: unknown): WebGroundingSummary | null {
  const report = asRecord(value);
  if (!report) return null;

  const sourceValues = Array.isArray(report.sources) ? report.sources : [];
  const sources: WebGroundingSourceSummary[] = [];
  for (const value of sourceValues) {
    const source = asRecord(value);
    if (!source) continue;
    const sourceId = nonEmptyString(source.source_id);
    const kind = source.kind;
    if (!sourceId || (kind !== "page" && kind !== "asset")) continue;

    if (kind === "page") {
      const url = nonEmptyString(source.final_url) ?? nonEmptyString(source.requested_url);
      if (!url) continue;
      sources.push({
        sourceId,
        kind,
        label: nonEmptyString(source.title) ?? url,
        url,
        assetId: null
      });
    } else {
      const assetId = nonEmptyString(source.asset_id);
      if (!assetId) continue;
      sources.push({
        sourceId,
        kind,
        label: nonEmptyString(source.label) ?? nonEmptyString(source.title) ?? assetId,
        url: null,
        assetId
      });
    }
  }

  const citationCount = Array.isArray(report.citations) ? report.citations.length : 0;
  if (sources.length === 0 && citationCount === 0) return null;
  return { sources, citationCount };
}
