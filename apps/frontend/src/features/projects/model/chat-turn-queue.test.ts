import assert from "node:assert/strict";
import test from "node:test";
import type { ChatAttachmentRef } from "./chat-attachments";
import {
  applyTurnStateOverrides,
  MessageSubmissionGuard,
  reconcileTurnStateOverrides,
  selectTurnQueueState,
  type ChatTurn,
  type TurnState,
} from "./chat-turn";

function turn(turnId: string, state: TurnState, requestedAt: string): ChatTurn {
  return {
    turnId,
    threadId: "thread-r5",
    projectId: "project-r5",
    state,
    requestedAt,
    lastEventId: null,
    generationAttempts: state === "queued" ? 0 : 1,
    submissionMessage: null,
    derivation: null,
  };
}

test("queue selectors keep busy, running, and ordered queued turns distinct", () => {
  const selected = selectTurnQueueState([
    turn("turn-a", "running", "2026-08-10T01:00:00Z"),
    turn("turn-b", "queued", "2026-08-10T01:00:01Z"),
    turn("turn-c", "queued", "2026-08-10T01:00:02Z"),
  ]);

  assert.equal(selected.threadBusy, true);
  assert.equal(selected.runningTurn?.turnId, "turn-a");
  assert.deepEqual(selected.queuedTurns.map((item) => item.turnId), [
    "turn-b",
    "turn-c",
  ]);
});

test("a queued-only thread stays busy without exposing a Stop target", () => {
  const selected = selectTurnQueueState([
    turn("turn-b", "queued", "2026-08-10T01:00:01Z"),
  ]);

  assert.equal(selected.threadBusy, true);
  assert.equal(selected.runningTurn, null);
  assert.deepEqual(selected.queuedTurns.map((item) => item.turnId), ["turn-b"]);
});

test("a terminal stream frame overrides a stale running read until it catches up", () => {
  const stale = [turn("turn-a", "running", "2026-08-10T01:00:00Z")];
  const override = new Map<string, TurnState>([["turn-a", "cancelled"]]);

  assert.equal(applyTurnStateOverrides(stale, override)[0].state, "cancelled");
  assert.equal(reconcileTurnStateOverrides(override, stale), override);

  const fresh = [turn("turn-a", "cancelled", "2026-08-10T01:00:00Z")];
  assert.equal(reconcileTurnStateOverrides(override, fresh).size, 0);
});

test("a durable terminal read supersedes an older running stream override", () => {
  const terminal = [turn("turn-a", "failed", "2026-08-10T01:00:00Z")];
  const override = new Map<string, TurnState>([["turn-a", "running"]]);
  const reconciled = reconcileTurnStateOverrides(override, terminal);

  assert.equal(reconciled.size, 0);
  assert.equal(applyTurnStateOverrides(terminal, reconciled)[0].state, "failed");
});

test("message duplicate protection blocks only the exact in-flight request", () => {
  const guard = new MessageSubmissionGuard();
  let key = 0;
  const submission = (
    message: string,
    agentProfileId = "head-of-abm@v30",
    attachmentRefs: ChatAttachmentRef[] = [],
  ) => ({
    message,
    contextRefs: [],
    attachmentRefs,
    agentProfileId,
  });
  const first = guard.begin(
    "thread-r5",
    submission("same message"),
    () => `key-${++key}`,
  );
  assert.ok(first);
  assert.equal(
    guard.begin(
      "thread-r5",
      submission("same message"),
      () => `key-${++key}`,
    ),
    null,
  );
  const different = guard.begin(
    "thread-r5",
    submission("different message"),
    () => `key-${++key}`,
  );
  assert.ok(different);
  assert.ok(
    guard.begin(
      "thread-r5",
      submission("same message", "another-profile@v1"),
      () => `key-${++key}`,
    ),
  );
  // The same words carrying a file are a different request, not a duplicate.
  assert.ok(
    guard.begin(
      "thread-r5",
      submission("same message", "head-of-abm@v30", [
        {
          uploadId: "upl_1",
          artifactKey: `ws_1/${"a".repeat(64)}`,
          sha256: "a".repeat(64),
          mediaType: "text/markdown",
          byteCount: 12,
          filename: "brief.md",
        },
      ]),
      () => `key-${++key}`,
    ),
  );
  guard.finish(first);
  assert.ok(
    guard.begin(
      "thread-r5",
      submission("same message"),
      () => `key-${++key}`,
    ),
  );
});
