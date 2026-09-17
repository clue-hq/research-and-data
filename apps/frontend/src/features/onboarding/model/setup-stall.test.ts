import assert from "node:assert/strict";
import test from "node:test";
import {
  MAX_STALL_POLLS,
  isStalled,
  progressSignature,
  shouldStopSetupPolling,
  stallAdvance,
  type SetupStallSnapshot,
} from "./setup-stall";

const STARTING: SetupStallSnapshot = {
  status: "starting",
  steps: [],
};

function withSteps(
  base: SetupStallSnapshot,
  steps: SetupStallSnapshot["steps"],
): SetupStallSnapshot {
  return { ...base, steps };
}

test("a first observation is never a stall — learning the state is progress", () => {
  assert.equal(stallAdvance(null, STARTING, 0), 0);
  assert.equal(stallAdvance(null, { status: "running" }, 39), 0);
});

test("an unchanged in-flight tick increments, in both in-flight statuses", () => {
  assert.equal(stallAdvance(STARTING, STARTING, 0), 1);
  assert.equal(stallAdvance(STARTING, STARTING, 7), 8);
  const running: SetupStallSnapshot = {
    status: "running",
    steps: [{ kind: "overview", subjectRef: null, status: "running" }],
  };
  assert.equal(stallAdvance(running, { ...running }, 3), 4);
});

test("a new step resets the count — a slow but alive lane is never cut off", () => {
  const seen = withSteps(STARTING, [{ kind: "overview", subjectRef: null, status: "running" }]);
  assert.equal(stallAdvance(STARTING, seen, 39), 0);
  // …and a second step appearing is motion too.
  const both = withSteps(STARTING, [
    { kind: "overview", subjectRef: null, status: "running" },
    { kind: "lineup", subjectRef: null, status: "queued" },
  ]);
  assert.equal(stallAdvance(seen, both, 39), 0);
});

test("a step status change with no new step still counts as motion", () => {
  const before = withSteps(STARTING, [{ kind: "overview", subjectRef: null, status: "running" }]);
  const after = withSteps(STARTING, [{ kind: "overview", subjectRef: null, status: "completed" }]);
  assert.equal(stallAdvance(before, after, 12), 0);
  assert.equal(stallAdvance(after, { ...after }, 7), 8);
});

test("per-subject steps are distinguished by their subject, not only their kind", () => {
  // The background persona steps all share one kind; only `subjectRef` tells them apart, so a
  // second persona starting must read as motion rather than as an unchanged tick.
  const one = withSteps(
    { status: "running" },
    [{ kind: "persona", subjectRef: "clue-abm-buyers", status: "running" }],
  );
  const two = withSteps(
    { status: "running" },
    [
      { kind: "persona", subjectRef: "clue-abm-buyers", status: "running" },
      { kind: "persona", subjectRef: "clue-abm-champions", status: "running" },
    ],
  );
  assert.equal(stallAdvance(one, two, 39), 0);
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
  // The fast steps completing is the release signal — it must reset, not trip, the bound.
  assert.equal(stallAdvance(STARTING, { ...STARTING, status: "complete" }, MAX_STALL_POLLS), 0);
});

test("isStalled trips exactly at the 60s budget, not before", () => {
  assert.equal(isStalled(MAX_STALL_POLLS - 1), false);
  assert.equal(isStalled(MAX_STALL_POLLS), true);
  assert.equal(MAX_STALL_POLLS, 40); // 40 × 1.5s = 60s, the same budget the `none` path uses
});

test("stall fallback keeps polling while true backend terminals stop", () => {
  assert.equal(shouldStopSetupPolling("stalled"), false);
  assert.equal(shouldStopSetupPolling("session"), false);
  assert.equal(shouldStopSetupPolling(null), false);
  assert.equal(shouldStopSetupPolling("failed"), true);
  assert.equal(shouldStopSetupPolling("unavailable"), true);
});

test("the signature ignores payload that is not progress", () => {
  const a: SetupStallSnapshot = { status: "running", steps: [] };
  const b: SetupStallSnapshot = { status: "running", steps: [] };
  assert.equal(progressSignature(a), progressSignature(b));
  // An absent step list reads the same as an explicit empty one, and an absent `subjectRef` the
  // same as an explicit null — two payloads describing one state must not look like motion.
  assert.equal(progressSignature({ status: "starting" }), progressSignature(STARTING));
  assert.equal(
    progressSignature({ status: "running", steps: [{ kind: "overview", status: "running" }] }),
    progressSignature({
      status: "running",
      steps: [{ kind: "overview", subjectRef: null, status: "running" }],
    }),
  );
});

test("a dead driver reaches the terminal after exactly the budget of unchanged ticks", () => {
  // The end-to-end shape of the fix: `starting` forever (the durable run row means the read
  // surface never serves `none` again), nothing else ever moving.
  let count = 0;
  let previous: SetupStallSnapshot | null = null;
  for (let tick = 0; tick < MAX_STALL_POLLS + 1; tick += 1) {
    count = stallAdvance(previous, STARTING, count);
    previous = STARTING;
    assert.equal(isStalled(count), tick === MAX_STALL_POLLS);
  }
});
