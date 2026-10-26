import { describe, expect, it } from "vitest";
import { isTerminalJob, type IngestJob } from "../brandLibrary";

function job(status: string): IngestJob {
  return {
    job_id: "ingest_1",
    kind: "website",
    status,
    stage: null,
    progress: 1,
    brand_kit_id: "kit_1",
    brand_kit_version: 1,
    error: null,
    created_at: "2026-10-25T00:00:00Z",
    updated_at: "2026-10-25T00:00:00Z",
  };
}

describe("isTerminalJob", () => {
  it("treats a job that finished with gaps as finished, so polling stops (spec 2026-10-25)", () => {
    expect(isTerminalJob(job("succeeded_with_gaps"))).toBe(true);
    expect(isTerminalJob(job("succeeded"))).toBe(true);
    expect(isTerminalJob(job("failed"))).toBe(true);
    expect(isTerminalJob(job("running"))).toBe(false);
  });
});
