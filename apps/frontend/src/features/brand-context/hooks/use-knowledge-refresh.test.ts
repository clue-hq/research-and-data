import assert from "node:assert/strict";
import { test } from "node:test";

import { shouldRefresh } from "./use-knowledge-refresh";

const step = (kind: string, finishedAt: string | null) => ({ costUsd: "0", failureCode: null, finishedAt, kind, phase: "fast", startedAt: "2026-09-08T00:00:00Z", status: finishedAt ? "completed" : "running", subjectRef: null });
const status = (steps: ReturnType<typeof step>[], runStatus = "running") => ({ costUsd: "0", runId: "r", status: runStatus, steps });

test("a newly finished step asks for a refresh; nothing else does", () => {
  assert.equal(shouldRefresh(status([step("overview", null)]), status([step("overview", "2026-09-08T00:01:00Z")])), true);
  assert.equal(shouldRefresh(status([step("overview", null)]), status([step("overview", null)])), false);
  assert.equal(shouldRefresh(null, status([step("overview", "2026-09-08T00:01:00Z")])), true);
  assert.equal(shouldRefresh(status([step("overview", "2026-09-08T00:01:00Z")]), null), false);
});

test("a run going terminal refreshes once so the last documents land", () => {
  const before = status([step("overview", "2026-09-08T00:01:00Z")]);
  const after = status([step("overview", "2026-09-08T00:01:00Z")], "completed");
  assert.equal(shouldRefresh(before, after), true);
});
