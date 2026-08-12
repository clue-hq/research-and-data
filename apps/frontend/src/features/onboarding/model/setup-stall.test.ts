import assert from "node:assert/strict";
import test from "node:test";
import {
  MAX_STALL_POLLS,
  isStalled,
  progressSignature,
  stallAdvance,
  type SetupStallSnapshot,
} from "./setup-stall";

const STARTING: SetupStallSnapshot = {
  status: "starting",
  fast_status: null,
  background_status: null,
  fields: [],
};

function withFields(
  base: SetupStallSnapshot,
  fields: SetupStallSnapshot["fields"],
): SetupStallSnapshot {
  return { ...base, fields };
}

test("a first observation is never a stall — learning the state is progress", () => {
  assert.equal(stallAdvance(null, STARTING, 0), 0);
  assert.equal(stallAdvance(null, { status: "running" }, 39), 0);
});

test("an unchanged in-flight tick increments, in both in-flight statuses", () => {
  assert.equal(stallAdvance(STARTING, STARTING, 0), 1);
  assert.equal(stallAdvance(STARTING, STARTING, 7), 8);
  const running = { status: "running", fast_status: "running" };
  assert.equal(stallAdvance(running, { ...running }, 3), 4);
});

test("a new field event resets the count — a slow but alive lane is never cut off", () => {
  const seen = withFields(STARTING, [
    { field_key: "client.value_prop", lane: "fast", status: "started" },
  ]);
  assert.equal(stallAdvance(STARTING, seen, 39), 0);
  // …and a field moving from started to resolved is motion too.
  const resolved = withFields(STARTING, [
    { field_key: "client.value_prop", lane: "fast", status: "resolved" },
  ]);
  assert.equal(stallAdvance(seen, resolved, 39), 0);
});

test("a lane transition with no new field event still counts as motion", () => {
  const before = { status: "running", fast_status: "running", background_status: "queued" };
  const after = { status: "running", fast_status: "completed", background_status: "running" };
  assert.equal(stallAdvance(before, after, 12), 0);
});

test("an overall status change resets the count", () => {
  assert.equal(stallAdvance(STARTING, { ...STARTING, status: "running" }, 20), 0);
});

test("statuses that are not in-flight never accumulate a stall", () => {
  // `none` has its own budget; the terminals are surfaced by their own branches. An unchanging
  // tick in any of them is correct, not a stall.
  for (const status of ["none", "complete", "failed", "unavailable"]) {
    assert.equal(stallAdvance({ status }, { status }, 39), 0, status);
  }
});

test("the release tick can never be swallowed by an accumulated stall", () => {
  // The fast lane completing is the release signal — it must reset, not trip, the bound.
  assert.equal(stallAdvance(STARTING, { ...STARTING, status: "complete" }, MAX_STALL_POLLS), 0);
});

test("isStalled trips exactly at the 60s budget, not before", () => {
  assert.equal(isStalled(MAX_STALL_POLLS - 1), false);
  assert.equal(isStalled(MAX_STALL_POLLS), true);
  assert.equal(MAX_STALL_POLLS, 40); // 40 × 1.5s = 60s, the same budget the `none` path uses
});

test("the signature ignores payload that is not progress", () => {
  const a = { status: "running", fields: [] } as SetupStallSnapshot;
  const b = { status: "running", fields: [] } as SetupStallSnapshot;
  assert.equal(progressSignature(a), progressSignature(b));
  // Absent optional lane statuses read the same as explicit nulls — a pre-slice-3 payload and a
  // slice-3 one describing the same state must not look like motion to each other.
  assert.equal(
    progressSignature({ status: "starting" }),
    progressSignature({ status: "starting", fast_status: null, background_status: null, fields: [] }),
  );
});

test("a dead driver reaches the terminal after exactly the budget of unchanged ticks", () => {
  // The end-to-end shape of the fix: `starting` forever (the durable input row means the read
  // surface never serves `none` again), nothing else ever moving.
  let count = 0;
  let previous: SetupStallSnapshot | null = null;
  for (let tick = 0; tick < MAX_STALL_POLLS + 1; tick += 1) {
    count = stallAdvance(previous, STARTING, count);
    previous = STARTING;
    assert.equal(isStalled(count), tick === MAX_STALL_POLLS);
  }
});
