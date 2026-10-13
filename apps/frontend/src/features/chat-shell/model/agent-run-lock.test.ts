import assert from "node:assert/strict";
import { test } from "node:test";
import {
  AGENT_RUN_LOCK_NOTE,
  AGENT_RUN_PUBLISH_NOTE,
  NO_AGENT_RUN,
  UNKNOWN_DESIGN_LEG,
  agentRunLockForThread,
  applyAgentRunLockEvent,
  designLegFactFor,
  type AgentRunLockFrame,
  type AgentRunLockState,
  type DesignLegFact,
} from "./agent-run-lock";

/**
 * Scene live-streaming rung A, task 4: the editor lock's whole decision.
 *
 * Everything the surface does about the lock is decided here, so the engage /
 * release matrix can be proven against synthetic frames with no React, no
 * canvas and no wasm — the same discipline `artifact-auto-open` and
 * `design-leg` follow.
 *
 * Fix round 1 adds the two dangerous-direction cases the controller found: a
 * leg the stream has NOT observed must not read as "no leg" (I1), and one
 * turn's hand-back must not release another turn's run (I2).
 */

const THREAD = "thread-design";
const OTHER_THREAD = "thread-other";
const DOCUMENT = "doc-ad-1";

const OPEN_LEG: DesignLegFact = { kind: "open", running: false };

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
    designLeg: OPEN_LEG,
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

test("the publish copy is the founder's sentence, verbatim (2026-10-13)", () => {
  assert.equal(
    AGENT_RUN_PUBLISH_NOTE,
    "The design agent is working — publishing unlocks when it finishes.",
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
  test(`${terminal} releases its own turn even while the queue still reads busy`, () => {
    const state = frames(frame("turn.accepted"), frame(terminal));
    assert.equal(lockFor(state, { threadBusy: true }).locked, false);
  });
}

/* --------------------------------------------------------------------------
 * I2 — a leg frame releases ONE turn, never the whole run
 * ----------------------------------------------------------------------- */

test("a previous turn's late hand-back does NOT release the run in flight", () => {
  // Per-turn backlog attaches have no cross-turn ordering, and EVERY design
  // turn ends with `leg.awaiting_user`. Clearing every active turn on one of
  // them unlocked the editor mid-run — the exact dangerous direction.
  const state = frames(
    frame("turn.accepted", { turnId: "turn-N" }),
    frame("leg.awaiting_user", { turnId: "turn-N-minus-1" }),
  );
  assert.equal(lockFor(state, { threadBusy: true }).locked, true);
});

test("...and the run's OWN hand-back still releases it", () => {
  const state = frames(
    frame("turn.accepted", { turnId: "turn-N" }),
    frame("leg.awaiting_user", { turnId: "turn-N-minus-1" }),
    frame("leg.awaiting_user", { turnId: "turn-N" }),
  );
  assert.equal(lockFor(state, { threadBusy: true }).locked, false);
});

test("a hand-back for a turn nobody saw start still lifts the busy floor", () => {
  // Nothing is left running, so the durable `threadBusy` floor has nothing to
  // stand on — this is what releases a cold-loaded lock at the hand-back.
  const state = frames(frame("leg.awaiting_user", { turnId: "turn-N" }));
  assert.equal(lockFor(state, { threadBusy: true }).locked, false);
});

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

/* --------------------------------------------------------------------------
 * I1 — an UNOBSERVED leg is not "no leg"
 * ----------------------------------------------------------------------- */

test("active turn observed, leg not yet observed → locked", () => {
  // The dangerous direction the controller found: `designLegOpen` was seeded
  // CLOSED and moved only by leg frames, and rehydration replays three turns —
  // so a cold load into a leg opened further back read as "no design leg" and
  // unlocked the editor mid-run.
  assert.equal(
    lockFor(frames(frame("turn.accepted")), { designLeg: UNKNOWN_DESIGN_LEG })
      .locked,
    true,
  );
});

test("an unobserved leg plus a busy thread is locked, with no frames at all", () => {
  assert.equal(
    lockFor(NO_AGENT_RUN, { designLeg: UNKNOWN_DESIGN_LEG, threadBusy: true })
      .locked,
    true,
  );
});

test("an unobserved leg with nothing running at all stays unlocked", () => {
  assert.equal(
    lockFor(NO_AGENT_RUN, { designLeg: UNKNOWN_DESIGN_LEG, threadBusy: false })
      .locked,
    false,
  );
});

test("the durable wire says RUNNING and no frames have arrived → locked", () => {
  assert.equal(
    lockFor(NO_AGENT_RUN, {
      designLeg: { kind: "open", running: true },
      threadBusy: false,
    }).locked,
    true,
  );
});

test("the wire's running floor yields to an observed terminal frame", () => {
  // The wire is a snapshot taken at load; once the stream says the run handed
  // back, a stale "running" must not hold the editor shut forever.
  const state = frames(frame("turn.accepted"), frame("leg.awaiting_user"));
  assert.equal(
    lockFor(state, { designLeg: { kind: "open", running: true } }).locked,
    false,
  );
});

test("the wire says open_awaiting_user, no frames, not busy → unlocked", () => {
  assert.equal(
    lockFor(NO_AGENT_RUN, {
      designLeg: { kind: "open", running: false },
      threadBusy: false,
    }).locked,
    false,
  );
});

test("a thread the platform says has NO leg is the one unlocked-by-default state", () => {
  assert.equal(
    lockFor(frames(frame("turn.accepted")), { designLeg: { kind: "none" } })
      .locked,
    false,
  );
});

/* --------------------------------------------------------------------------
 * The leg fact itself — stream observation over durable wire
 * ----------------------------------------------------------------------- */

test("nothing observed and no wire is UNKNOWN, never 'no leg'", () => {
  assert.deepEqual(
    designLegFactFor({ leg: { known: false, open: false }, wire: null }),
    UNKNOWN_DESIGN_LEG,
  );
});

test("the durable wire answers while the stream has observed nothing", () => {
  assert.deepEqual(
    designLegFactFor({
      leg: { known: false, open: false },
      wire: { legId: "leg-9", state: "running" },
    }),
    { kind: "open", running: true },
  );
  assert.deepEqual(
    designLegFactFor({
      leg: { known: false, open: false },
      wire: { legId: null, state: null },
    }),
    { kind: "none" },
  );
});

test("an OBSERVED stream leg outranks the wire snapshot it was taken from", () => {
  // The wire is a load-time snapshot; the frames are live. A leg the stream
  // watched close is closed, whatever the list read said a minute ago.
  assert.deepEqual(
    designLegFactFor({
      leg: { known: true, open: false },
      wire: { legId: "leg-9", state: "running" },
    }),
    { kind: "none" },
  );
});

test("the wire's RUNNING flag survives an observed open leg", () => {
  assert.deepEqual(
    designLegFactFor({
      leg: { known: true, open: true },
      wire: { legId: "leg-9", state: "running" },
    }),
    { kind: "open", running: true },
  );
});

/* --------------------------------------------------------------------------
 * Document binding
 * ----------------------------------------------------------------------- */

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

/* A handoff opens an empty document. The subsequent turn does the designing. */
function handoffOpener() {
  return ["turn.accepted", "turn.started", "leg.opened", "turn.awaiting_input"]
    .map((type) => frame(type, { turnId: "opener" }));
}

for (const terminal of [
  "turn.failed", "turn.completed", "turn.cancelled", "leg.awaiting_user", "leg.closed",
]) {
  test(`an awaiting-input handoff does not pin the editor after Design ${terminal}`, () => {
    const running = frames(...handoffOpener(), frame("turn.accepted"), frame("turn.started"));
    assert.equal(lockFor(running).locked, true);
    const settled = applyAgentRunLockEvent(running, frame(terminal));
    assert.deepEqual(lockFor(settled, {
      threadBusy: true,
      designLeg: { kind: "open", running: true },
    }), { locked: false, note: null });
  });
}

test("cold replay can finish Design before replaying its older handoff opener", () => {
  const settled = frames(
    frame("turn.accepted"), frame("turn.started"),
    frame("leg.awaiting_user"), frame("turn.failed"),
    ...handoffOpener(),
  );
  assert.equal(lockFor(settled, { threadBusy: true }).locked, false);
});

test("an ordinary awaiting-input Design gate keeps the editor locked", () => {
  const parked = frames(frame("turn.accepted"), frame("turn.awaiting_input"));
  assert.equal(lockFor(parked).locked, true);
});

test("reopening a leg does not classify a turn as a new-document handoff", () => {
  const parked = frames(frame("turn.accepted"), frame("leg.reopened"), frame("turn.awaiting_input"));
  assert.equal(lockFor(parked).locked, true);
});

test("a late opener terminal cannot release a newer writer, including a parked writer", () => {
  for (const last of ["turn.started", "turn.awaiting_input"]) {
    const running = frames(
      ...handoffOpener().slice(0, -1),
      frame("turn.accepted"), frame(last),
      ...handoffOpener().slice(-1),
    );
    assert.equal(lockFor(running).locked, true);
    assert.equal(lockFor(applyAgentRunLockEvent(running, frame("turn.failed", { turnId: "opener" }))).locked, true);
  }
});

test("an opener on another thread cannot classify this thread's awaiting-input turn", () => {
  const state = frames(
    frame("turn.accepted", { threadId: OTHER_THREAD }),
    frame("leg.opened", { threadId: OTHER_THREAD }),
    frame("turn.accepted"), frame("turn.awaiting_input"),
  );
  assert.equal(lockFor(state).locked, true);
});

for (const release of ["turn.completed", "turn.failed", "turn.cancelled", "leg.awaiting_user", "leg.closed", "turn.awaiting_input", "stream.reset"]) {
  test(`${release} forgets the opener classification before another attempt`, () => {
    const state = frames(
      frame("turn.accepted"), frame("leg.opened"), frame(release),
      frame("turn.started"), frame("turn.awaiting_input"),
    );
    assert.equal(lockFor(state).locked, true);
  });
}

test("a handoff frame without an observed active turn cannot label a future writer", () => {
  const state = frames(frame("leg.opened"), frame("turn.started"), frame("turn.awaiting_input"));
  assert.equal(lockFor(state).locked, true);
});
