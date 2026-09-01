import assert from "node:assert/strict";
import { test } from "node:test";
import { AGENT_RUN_LOCK_NOTE } from "@/features/chat-shell/model/agent-run-lock";
import {
  engageSceneWriteLock,
  sceneManualWriteGate,
} from "./use-scene-manual-edits";

/**
 * Scene live-streaming rung A, task 4 — the ad lane's write gate, tested as the
 * pure decision it is (the `canvasWriteTarget` / `createSceneReplaceImageHandler`
 * precedent: a React hook cannot be exercised without a DOM, a function can).
 *
 * Two things are pinned here, and they are the two the lock actually turns on:
 * what a write is refused FOR (and whether that refusal says anything), and the
 * ORDER of the lock-engage transition — the open caret session is flushed
 * BEFORE the latch closes, so typed work is committed rather than stranded
 * behind a gate that has already shut.
 */

const ARMED = { armed: true, engineReady: true, lockNote: AGENT_RUN_LOCK_NOTE };

test("an armed, unlocked lane may write, and says nothing", () => {
  assert.deepEqual(sceneManualWriteGate({ ...ARMED, locked: false }), {
    allowed: true,
    note: null,
    refusal: null,
  });
});

test("the agent-run lock refuses the write AND carries the reason", () => {
  assert.deepEqual(sceneManualWriteGate({ ...ARMED, locked: true }), {
    allowed: false,
    note: AGENT_RUN_LOCK_NOTE,
    refusal: "agent_run",
  });
});

test("the lock outranks the lane's own two silent refusals", () => {
  // Locked and unarmed at once still reports the LOCK: it is the refusal the
  // human can do something about (wait), and the only one with words.
  assert.equal(
    sceneManualWriteGate({
      ...ARMED,
      armed: false,
      engineReady: false,
      locked: true,
    }).refusal,
    "agent_run",
  );
});

test("an unarmed lane is refused in silence, exactly as it was", () => {
  assert.deepEqual(
    sceneManualWriteGate({ ...ARMED, armed: false, locked: false }),
    { allowed: false, note: null, refusal: "not_armed" },
  );
});

test("a dead engine is refused in silence (the G-D banner already says it)", () => {
  assert.deepEqual(
    sceneManualWriteGate({ ...ARMED, engineReady: false, locked: false }),
    { allowed: false, note: null, refusal: "engine_unavailable" },
  );
});

test("a lock with no copy still refuses; it just has nothing to say", () => {
  assert.deepEqual(
    sceneManualWriteGate({ ...ARMED, lockNote: null, locked: true }),
    { allowed: false, note: null, refusal: "agent_run" },
  );
});

/** A transition recorder: what the lock edge did, and in what order. */
function transitionSpy() {
  const calls: string[] = [];
  let latch = false;
  return {
    calls,
    latch: () => latch,
    run(locked: boolean) {
      latch = engageSceneWriteLock({
        announce: () => calls.push("announce"),
        flush: () => {
          calls.push("flush");
          // The ordering contract: the session's own commit rides the SAME
          // `applyOps` the inspector uses, so it must still be allowed when it
          // runs.
          assert.equal(latch, false, "the flush must run BEFORE the latch closes");
        },
        locked,
        previous: latch,
        withdraw: () => calls.push("withdraw"),
      });
      return latch;
    },
  };
}

test("engaging the lock flushes the open text session first, then announces", () => {
  // Task 4 fix round 1 (I4): the reason is PROACTIVE. It used to appear only
  // once the human tried something and was refused, so a locked editor sat
  // there inert with nothing on screen explaining it.
  const spy = transitionSpy();

  assert.equal(spy.run(true), true);
  assert.deepEqual(spy.calls, ["flush", "announce"]);

  // Still locked on the next render: no edge, so nothing fires again.
  assert.equal(spy.run(true), true);
  assert.deepEqual(spy.calls, ["flush", "announce"]);
});

test("releasing the lock withdraws the reason and flushes nothing", () => {
  const spy = transitionSpy();
  spy.run(true);
  spy.calls.length = 0;

  assert.equal(spy.run(false), false);
  assert.deepEqual(spy.calls, ["withdraw"]);
});

test("staying unlocked is a complete non-event", () => {
  const spy = transitionSpy();
  assert.equal(spy.run(false), false);
  assert.deepEqual(spy.calls, []);
});
