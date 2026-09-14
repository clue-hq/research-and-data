import assert from "node:assert/strict";
import { test } from "node:test";
import type { ChatStreamEvent } from "./chat-events";
import { ChatPartSnapshotSchema } from "./chat-parts";
import { ProjectPlanWriteTracker } from "./plan-write-signal";

function event(eventId: number | null, partId = "plan:new", turnId = "turn") {
  return {
    eventId,
    turnId,
    type: "part.created" as const,
    part: ChatPartSnapshotSchema.parse({
      part_id: partId, kind: "plan", revision: 1, title: "Plan",
      plan_ref: { object_type: "project_document", object_id: partId },
    }),
  };
}

test("Plan history arriving after initial loading finishes never opens the tab", () => {
  const tracker = new ProjectPlanWriteTracker();
  tracker.seedHistory([{ turnId: "turn", lastEventId: 100 }]);
  assert.equal(tracker.observe(event(90, "plan:old")), false);
  assert.equal(tracker.observe(event(100, "plan:boundary")), false);
  assert.equal(tracker.observe(event(101)), true);
});

test("repeated delivery and a later snapshot of the same plan open at most once", () => {
  const tracker = new ProjectPlanWriteTracker();
  assert.equal(tracker.observe(event(1)), true);
  assert.equal(tracker.observe(event(1)), false);
  assert.equal(tracker.observe(event(2)), false);
  assert.equal(tracker.observe(event(3, "plan:next-version")), true);
});

test("reconnect keeps the original cursor and never swallows a write missed during disconnect", () => {
  const tracker = new ProjectPlanWriteTracker();
  tracker.seedHistory([{ turnId: "turn", lastEventId: 100 }]);
  tracker.seedHistory([{ turnId: "turn", lastEventId: 130 }]);
  assert.equal(tracker.observe(event(120)), true);
  tracker.seedHistory([{ turnId: "older-turn", lastEventId: 80 }]);
  assert.equal(tracker.observe(event(75, "plan:older", "older-turn")), false);
});

test("a newly submitted turn starts at zero even if the next read already includes its write", () => {
  const tracker = new ProjectPlanWriteTracker();
  tracker.seedHistory([{ turnId: "new-turn", lastEventId: null }]);
  tracker.seedHistory([{ turnId: "new-turn", lastEventId: 200 }]);
  assert.equal(tracker.observe(event(200, "plan:new", "new-turn")), true);
});

test("unrelated, failed, and cursorless events cannot announce a Plan write", () => {
  const tracker = new ProjectPlanWriteTracker();
  assert.equal(tracker.observe(event(null)), false);
  assert.equal(tracker.observe({ ...event(1), type: "part.failed" }), false);
  assert.equal(tracker.observe({ ...event(2), part: null }), false);
  const unrelated: Pick<ChatStreamEvent, "type" | "part" | "eventId" | "turnId"> = {
    ...event(3),
    part: ChatPartSnapshotSchema.parse({
      part_id: "other", kind: "plan", revision: 1, title: "Other",
      plan_ref: { object_type: "design_document", object_id: "design" },
    }),
  };
  assert.equal(tracker.observe(unrelated), false);
  assert.equal(tracker.observe(event(4)), true);
});


test("a document part without a persistent ID cannot open a file tab", () => {
  const tracker = new ProjectPlanWriteTracker();
  const missing = { ...event(1), part: ChatPartSnapshotSchema.parse({
    part_id: "unaddressed", kind: "plan", revision: 1, title: "Draft",
    plan_ref: { object_type: "project_document" },
  }) };
  assert.equal(tracker.observe(missing), false);
  assert.equal(tracker.observe(event(2)), true);
});
