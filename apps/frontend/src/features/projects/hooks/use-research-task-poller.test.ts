import assert from "node:assert/strict";
import test from "node:test";
import {
  ChatPartSnapshotSchema,
  type ChatTaskPart,
  type PolledResearchTask,
} from "../model/chat-parts";
import {
  applyChatStreamEvent,
  emptyTranscriptState,
} from "../model/chat-transcript";
import type { ChatStreamEvent } from "../model/chat-events";
import {
  POLL_DELAY_MS,
  hasUnsettledResearchTask,
  streamTaskWakeSignature,
} from "./use-research-task-poller";

/**
 * The poller's two pure decisions: keep going while any task is still moving
 * or waiting on a human, and wake back up when the stream projects a task part
 * it has not seen. The hook around them owns only the timer and the fetch.
 */

function polledTask(
  state: string,
  runId = "r1",
): PolledResearchTask {
  const part = ChatPartSnapshotSchema.parse({
    part_id: `task:${runId}`,
    kind: "task",
    revision: 2,
    state,
    title: "account research",
    run_ref: { object_type: "entity_research_run", object_id: runId },
    counts: { total: 3, queued: 1, running: 1, completed: 1, partial: 0, blocked: 0, failed: 0 },
  }) as ChatTaskPart;
  return { turnId: "t1", part, fieldProgress: null };
}

test("polling continues while any task is active or blocked", () => {
  for (const state of [
    "queued",
    "scoping",
    "light_research",
    "deep_research",
    "synthesizing",
    "checkpoint",
    "needs_input",
  ]) {
    assert.equal(
      hasUnsettledResearchTask([polledTask("completed"), polledTask(state, "r2")]),
      true,
      state,
    );
  }
});

test("polling stops when every task has settled", () => {
  assert.equal(
    hasUnsettledResearchTask([
      polledTask("completed"),
      polledTask("partial", "r2"),
      polledTask("failed", "r3"),
      polledTask("suspended", "r4"),
    ]),
    false,
  );
  assert.equal(hasUnsettledResearchTask([]), false);
});

test("a streamed task part changes the wake signature; other parts never do", () => {
  const taskCreated: ChatStreamEvent = {
    schemaVersion: "1",
    type: "part.created",
    eventId: 1,
    sequence: 1,
    occurredAt: "2026-08-19T00:00:00Z",
    projectId: "p1",
    threadId: "th1",
    turnId: "t1",
    messageId: null,
    generationAttemptId: null,
    partId: "task:r1",
    partKind: "task",
    runId: "r1",
    deltaIndex: null,
    delta: null,
    status: null,
    failureCode: null,
    reason: null,
    replayed: false,
    part: ChatPartSnapshotSchema.parse({
      part_id: "task:r1",
      kind: "task",
      revision: 1,
      state: "queued",
      title: "account research",
      run_ref: { object_type: "entity_research_run", object_id: "r1" },
      counts: { total: 1, queued: 1, running: 0, completed: 0, partial: 0, blocked: 0, failed: 0 },
    }),
  };
  const empty = emptyTranscriptState();
  const withTask = applyChatStreamEvent(empty, taskCreated);
  assert.notEqual(streamTaskWakeSignature(withTask), streamTaskWakeSignature(empty));

  const reasoningCreated: ChatStreamEvent = {
    ...taskCreated,
    eventId: 2,
    partId: "reasoning:1",
    partKind: "reasoning",
    part: ChatPartSnapshotSchema.parse({
      part_id: "reasoning:1",
      kind: "reasoning",
      revision: 1,
      state: "active",
      round_ordinal: 1,
      started_at: "2026-08-19T00:00:00Z",
    }),
  };
  assert.equal(
    streamTaskWakeSignature(applyChatStreamEvent(withTask, reasoningCreated)),
    streamTaskWakeSignature(withTask),
  );
});

test("the poll cadence is the 3-second contract", () => {
  assert.equal(POLL_DELAY_MS, 3_000);
});
