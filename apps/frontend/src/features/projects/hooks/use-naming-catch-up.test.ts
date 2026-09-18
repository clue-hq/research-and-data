import assert from "node:assert/strict";
import test from "node:test";
import {
  NAMING_CATCH_UP_INTERVAL_MS,
  NAMING_CATCH_UP_MAX_TICKS,
  namingCatchUpSchedule,
} from "./use-naming-catch-up";

test("constants match the spec: every 5 s, at most 12 times", () => {
  assert.equal(NAMING_CATCH_UP_INTERVAL_MS, 5_000);
  assert.equal(NAMING_CATCH_UP_MAX_TICKS, 12);
});

test("no terminal event yet → nothing to schedule", () => {
  assert.equal(namingCatchUpSchedule({ namingPending: true, terminalRevision: 0 }), null);
});

test("a terminal event while a placeholder is visible schedules the bounded poll", () => {
  assert.deepEqual(namingCatchUpSchedule({ namingPending: true, terminalRevision: 1 }), {
    intervalMs: 5_000,
    maxTicks: 12,
  });
});

test("nothing pending → nothing scheduled, even after a terminal event", () => {
  assert.equal(namingCatchUpSchedule({ namingPending: false, terminalRevision: 3 }), null);
});
