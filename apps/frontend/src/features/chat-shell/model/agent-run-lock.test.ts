import assert from "node:assert/strict";
import { test } from "node:test";
import {
  AGENT_RUN_LOCK_NOTE,
  NO_AGENT_RUN,
  agentRunLockForThread,
  applyAgentRunLockEvent,
  type AgentRunLockFrame,
  type AgentRunLockState,
} from "./agent-run-lock";

/**
 * Scene live-streaming rung A, task 4: the editor lock's whole decision.
 *
 * Everything the surface does about the lock is decided here, so the engage /
 * release matrix can be proven against synthetic frames with no React, no
 * canvas and no wasm — the same discipline `artifact-auto-open` and
 * `design-leg` follow.
 */

const THREAD = "thread-design";
const OTHER_THREAD = "thread-other";
const DOCUMENT = "doc-ad-1";

function frames(...events: readonly AgentRunLockFrame[]): AgentRunLockState {
  return events.reduce(applyAgentRunLockEvent, NO_AGENT_RUN);
}

function frame(
  type: string,
  overrides: Partial<AgentRunLockFrame> = {},
): AgentRunLockFrame {
  return { threadId: THREAD, turnId: "turn-1", type, ...overrides };
}

/** The open document, bound to the thread, with a design leg open on it. */
function lockFor(
  state: AgentRunLockState,
  overrides: Partial<Parameters<typeof agentRunLockForThread>[0]> = {},
) {
  return agentRunLockForThread({
    activeThreadId: THREAD,
    designLegOpen: true,
    documentId: DOCUMENT,
    documentThreadId: THREAD,
    state,
    threadBusy: false,
    ...overrides,
  });
}

test("the lock copy is the ratified sentence, verbatim", () => {
  assert.equal(
    AGENT_RUN_LOCK_NOTE,
    "The design agent is working — editing unlocks when it finishes.",
  );
});

test("an accepted turn engages the lock, and carries the note", () => {
  assert.deepEqual(lockFor(frames(frame("turn.accepted"))), {
    locked: true,
    note: AGENT_RUN_LOCK_NOTE,
  });
});

test("a started turn engages the lock", () => {
  assert.equal(
    lockFor(frames(frame("turn.accepted"), frame("turn.started"))).locked,
    true,
  );
});

for (const terminal of ["turn.completed", "turn.failed", "turn.cancelled"]) {
  test(`${terminal} releases the lock`, () => {
    const state = frames(frame("turn.accepted"), frame(terminal));
    assert.deepEqual(lockFor(state), { locked: false, note: null });
  });
}

test("a FAILED run releases the lock even when the durable queue still reads busy", () => {
  // The one case the release matrix calls out by name: a failed run must never
  // leave a locked editor, so the frame's release outranks the (lagging)
  // durable turn-queue fact.
  const state = frames(frame("turn.accepted"), frame("turn.failed"));
  assert.equal(lockFor(state, { threadBusy: true }).locked, false);
});

for (const terminal of ["leg.awaiting_user", "leg.closed"]) {
  test(`${terminal} releases the lock even while its turn is still running`, () => {
    const state = frames(frame("turn.accepted"), frame(terminal));
    assert.equal(lockFor(state, { threadBusy: true }).locked, false);
  });
}

test("a second turn re-engages after a release", () => {
  const state = frames(
    frame("turn.accepted"),
    frame("turn.completed"),
    frame("turn.accepted", { turnId: "turn-2" }),
  );
  assert.equal(lockFor(state).locked, true);
});

test("one turn ending does not release while another is still running", () => {
  const state = frames(
    frame("turn.accepted"),
    frame("turn.accepted", { turnId: "turn-2" }),
    frame("turn.completed"),
  );
  assert.equal(lockFor(state).locked, true);
});

test("a stream reset forgets the run; the durable busy fact takes over again", () => {
  const state = frames(
    frame("turn.accepted"),
    frame("turn.completed"),
    frame("stream.reset"),
  );
  assert.equal(lockFor(state, { threadBusy: true }).locked, true);
});

test("no design leg on the thread is the one unlocked-by-default state", () => {
  assert.equal(
    lockFor(frames(frame("turn.accepted")), { designLegOpen: false }).locked,
    false,
  );
});

test("with no frames yet, a busy thread is locked (fail-safe)", () => {
  assert.equal(lockFor(NO_AGENT_RUN, { threadBusy: true }).locked, true);
  assert.equal(lockFor(NO_AGENT_RUN, { threadBusy: false }).locked, false);
});

test("a sibling thread's document is never locked by this thread's run", () => {
  assert.equal(
    lockFor(frames(frame("turn.accepted")), {
      documentThreadId: OTHER_THREAD,
    }).locked,
    false,
  );
});

test("a document whose thread cannot be resolved locks anyway (fail-safe)", () => {
  assert.equal(
    lockFor(frames(frame("turn.accepted")), { documentThreadId: null }).locked,
    true,
  );
});

test("no open document is nothing to lock", () => {
  assert.equal(
    lockFor(frames(frame("turn.accepted")), { documentId: null }).locked,
    false,
  );
});

test("no active thread is nothing to lock", () => {
  assert.equal(
    lockFor(frames(frame("turn.accepted")), { activeThreadId: null }).locked,
    false,
  );
});

test("a run observed on another thread never locks this one", () => {
  const state = frames(frame("turn.accepted", { threadId: OTHER_THREAD }));
  assert.equal(lockFor(state).locked, false);
});

test("frames this build does not act on leave the state untouched", () => {
  const engaged = frames(frame("turn.accepted"));
  assert.equal(
    applyAgentRunLockEvent(engaged, frame("design.checkpoint")),
    engaged,
  );
  assert.equal(applyAgentRunLockEvent(engaged, frame("text.delta")), engaged);
});
