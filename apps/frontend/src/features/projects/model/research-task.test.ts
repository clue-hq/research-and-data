import assert from "node:assert/strict";
import test from "node:test";
import {
  ChatPartSnapshotSchema,
  type ChatPart,
  type ChatTaskPart,
} from "./chat-parts";
import {
  aggregateResearchTasks,
  researchTaskModel,
} from "./research-task";

/** Task aggregation: one run is one visible task at one account or five hundred. */

function taskPart(
  overrides: Record<string, unknown> = {},
  counts: Record<string, number> = {},
): ChatTaskPart {
  const parsed = ChatPartSnapshotSchema.parse({
    part_id: "task:r1",
    kind: "task",
    revision: 1,
    state: "deep_research",
    title: "account research",
    run_ref: { object_type: "entity_research_run", object_id: "r1" },
    counts: { total: 2, queued: 0, running: 2, completed: 0, partial: 0, blocked: 0, failed: 0, ...counts },
    ...overrides,
  });
  return parsed as ChatTaskPart;
}

test("500 accounts render as one task with counts, not 500 cards", () => {
  const task = researchTaskModel(
    taskPart({}, { total: 500, running: 480, completed: 20 }),
  );
  assert.equal(task.total, 500);
  assert.equal(task.summary, "20 of 500 accounts settled");
  assert.equal(task.running, true);
  assert.equal(task.blocked, false);
});

test("one account renders the same task with singular copy", () => {
  const task = researchTaskModel(taskPart({ state: "completed" }, { total: 1, completed: 1 }));
  assert.equal(task.label, "Complete");
  assert.equal(task.summary, "1 of 1 account researched");
  assert.equal(task.running, false);
  assert.equal(task.terminal, true);
});

test("every designed activity state maps, including the recovery ones", () => {
  const expected: Record<string, { label: string; running: boolean; blocked: boolean }> = {
    queued: { label: "Queued", running: true, blocked: false },
    scoping: { label: "Scoping", running: true, blocked: false },
    light_research: { label: "Light research", running: true, blocked: false },
    checkpoint: { label: "Checkpoint", running: false, blocked: true },
    deep_research: { label: "Deep research", running: true, blocked: false },
    synthesizing: { label: "Synthesizing", running: true, blocked: false },
    completed: { label: "Complete", running: false, blocked: false },
    partial: { label: "Partial results preserved", running: false, blocked: false },
    needs_input: { label: "Needs input", running: false, blocked: true },
    failed: { label: "Failed", running: false, blocked: false },
    suspended: { label: "Suspended", running: false, blocked: false },
  };
  for (const [state, want] of Object.entries(expected)) {
    const task = researchTaskModel(taskPart({ state }));
    assert.equal(task.label, want.label, state);
    assert.equal(task.running, want.running, `${state} running`);
    assert.equal(task.blocked, want.blocked, `${state} blocked`);
  }
});

test("a suspended run is a supervised pause, not a failure", () => {
  const task = researchTaskModel(taskPart({ state: "suspended" }));
  assert.equal(task.terminal, true);
  assert.equal(task.activity, "suspended");
  assert.notEqual(task.activity, "failed");
});

test("step rows only appear for non-zero counts", () => {
  const task = researchTaskModel(
    taskPart({ state: "partial" }, { total: 3, completed: 2, partial: 1, running: 0 }),
  );
  assert.deepEqual(
    task.steps.map((step) => step.id),
    ["completed", "partial"],
  );
});

test("subjects routed to review are their own count and still render as partial", () => {
  const part = taskPart(
    { state: "partial" },
    { total: 3, completed: 1, partial: 1, running: 0, needs_review: 1 },
  );
  // The count is split on the wire...
  assert.equal(part.counts.needsReview, 1);
  assert.equal(part.counts.partial, 1);
  // ...and nothing the human reads moves: settled counts it, and it shares the Partial row.
  const task = researchTaskModel(part);
  assert.equal(task.summary, "3 of 3 accounts settled");
  assert.deepEqual(
    task.steps.map((step) => [step.id, step.count]),
    [
      ["completed", 1],
      ["partial", 2],
    ],
  );
});

test("a counts payload without needsReview still parses, as zero", () => {
  const parsed = ChatPartSnapshotSchema.parse({
    part_id: "task:r-old",
    kind: "task",
    revision: 1,
    state: "partial",
    title: "account research",
    run_ref: { object_type: "entity_research_run", object_id: "r-old" },
    counts: { total: 1, queued: 0, running: 0, completed: 0, partial: 1, blocked: 0, failed: 0 },
  }) as ChatTaskPart;
  assert.equal(parsed.counts.needsReview, 0);
  assert.equal(researchTaskModel(parsed).summary, "1 of 1 account settled");
});

test("two snapshots of one run collapse to the highest revision", () => {
  const parts: ChatPart[] = [
    taskPart({ revision: 1, state: "queued" }, { queued: 2, running: 0 }),
    taskPart({ revision: 3, state: "partial" }, { completed: 1, partial: 1, running: 0 }),
    taskPart({ revision: 2, state: "deep_research" }),
  ];
  const tasks = aggregateResearchTasks(parts);
  assert.equal(tasks.length, 1);
  assert.equal(tasks[0].activity, "partial");
});

test("two different runs stay two tasks", () => {
  const parts: ChatPart[] = [
    taskPart(),
    taskPart({
      part_id: "task:r2",
      run_ref: { object_type: "entity_research_run", object_id: "r2" },
    }),
  ];
  assert.equal(aggregateResearchTasks(parts).length, 2);
});

// --- the C3 poll merge ----------------------------------------------------

test("exception refs are surfaced without breaking the single-task rule", () => {
  const task = researchTaskModel(
    taskPart({
      state: "partial",
      exception_refs: [
        { object_type: "entity_research_job", object_id: "j9" },
        { object_type: "entity_research_job", object_id: "j12" },
      ],
    }),
  );
  assert.equal(task.exceptionCount, 2);
});
