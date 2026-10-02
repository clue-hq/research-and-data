import assert from "node:assert/strict";
import test from "node:test";
import { DiscoveryRunStatusSchema, discoveryRunLive } from "./discovery-status";

const base = {
  run_id: "r1",
  status: "in_progress",
  asked: 35,
  found: 12,
  verified: 4,
  shown: 3,
  started_at: "2026-09-12T10:00:00Z",
  finished_at: null,
};

test("a run is live while it is not started or in progress, and not otherwise", () => {
  assert.equal(discoveryRunLive(DiscoveryRunStatusSchema.parse(base)), true);
  assert.equal(discoveryRunLive(DiscoveryRunStatusSchema.parse({ ...base, status: "not_started" })), true);
  for (const status of ["completed", "needs_review", "suspended"]) {
    assert.equal(discoveryRunLive(DiscoveryRunStatusSchema.parse({ ...base, status })), false);
  }
  assert.equal(discoveryRunLive(null), false);
});

test("an unknown status parses as not live rather than breaking the poll", () => {
  assert.equal(discoveryRunLive(DiscoveryRunStatusSchema.parse({ ...base, status: "paused" })), false);
});
