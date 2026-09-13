import assert from "node:assert/strict";
import { test } from "node:test";
import { planWriteToOpen, projectPlanPartIds } from "./plan-write-signal";

const part = (partId: string, objectType = "project_document") => ({ kind: "plan", partId, planRef: { objectType } });

test("a newly delivered project-document plan opens once, newest first", () => {
  const transcript = [{ id: "message", parts: [part("old"), part("new")] }];
  assert.equal(planWriteToOpen({ transcript, knownPlanPartIds: new Set(["old"]) }), "new");
  assert.equal(planWriteToOpen({ transcript, knownPlanPartIds: new Set(projectPlanPartIds(transcript)) }), null);
});

test("cold history, unrelated plan refs and tool names do not open the Plan tab", () => {
  const transcript = [{ id: "message", parts: [part("history")] }];
  assert.equal(planWriteToOpen({ transcript, knownPlanPartIds: null }), null);
  assert.equal(planWriteToOpen({ transcript: [{ id: "message", parts: [part("other", "design_document"), { kind: "tool", partId: "tool" }] }], knownPlanPartIds: new Set() }), null);
});


test("loading older history does not reopen Plan, but a fresh part in a loaded message does", () => {
  const transcript = [
    { id: "older-page", parts: [part("old-plan")] },
    { id: "loaded", parts: [part("fresh-plan")] },
  ];
  assert.equal(planWriteToOpen({ transcript, knownPlanPartIds: new Set(["fresh-plan"]), historyStartId: "loaded" }), null);
  assert.equal(planWriteToOpen({ transcript, knownPlanPartIds: new Set(), historyStartId: "loaded" }), "fresh-plan");
});
