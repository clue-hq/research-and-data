import assert from "node:assert/strict";
import test, { mock } from "node:test";
import {
  DESIGN_CHECKPOINT_CANVAS_RELOAD_MIN_INTERVAL_MS,
  throttleTrailing,
} from "./design-checkpoint-throttle";

/**
 * The rate limit on the mid-run canvas reload (scene live-streaming rung A).
 *
 * A generating scene commits a checkpoint every few seconds, and each one is a
 * durable new document version. Reloading the open canvas on every single one
 * would remount the editor faster than a person can look at it, so the bumps
 * are throttled — but the LAST checkpoint must never be the one that is
 * dropped, or the canvas would settle on a stale version and stay there with
 * nothing left to correct it. Hence trailing-edge, always.
 *
 * Driven on node:test's own fake clock: nothing here waits on real time.
 */

/** Run `body` with `setTimeout` faked, and always give the clock back. */
function onFakeClock(body: () => void): void {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    body();
  } finally {
    mock.timers.reset();
  }
}

/**
 * A fake clock that knows exactly what time it is inside a timer callback.
 *
 * `mock.timers.tick(n)` moves the clock to the END of the window before running
 * the callbacks due inside it, so a coarse tick reports a bump later than it
 * actually happened. Stepping one millisecond at a time removes that skew
 * entirely: a callback due at `t` runs in the step that lands on `t`.
 */
function steppedClock() {
  let now = 0;
  return {
    now: () => now,
    advance(ms: number) {
      for (let step = 0; step < ms; step += 1) {
        now += 1;
        mock.timers.tick(1);
      }
    },
  };
}

test("the interval is the ratified two seconds", () => {
  assert.equal(DESIGN_CHECKPOINT_CANVAS_RELOAD_MIN_INTERVAL_MS, 2000);
});

test("a single checkpoint bumps immediately and schedules nothing else", () => {
  onFakeClock(() => {
    let bumps = 0;
    const bump = throttleTrailing(() => {
      bumps += 1;
    }, 2000);

    bump();
    // The leading edge is synchronous: one checkpoint on a quiet run must not
    // wait two seconds to show up.
    assert.equal(bumps, 1);

    mock.timers.tick(10_000);
    assert.equal(bumps, 1, "a lone call must not bump twice");
    bump.cancel();
  });
});

test("five checkpoints in three seconds bump at 0s, at 2s, and once for the last", () => {
  onFakeClock(() => {
    const bumpsAt: number[] = [];
    const { now, advance } = steppedClock();
    const bump = throttleTrailing(() => {
      bumpsAt.push(now());
    }, 2000);

    bump(); // frame 1, t=0    — the leading edge
    advance(750);
    bump(); // frame 2, t=750  — inside the window, held
    advance(750);
    bump(); // frame 3, t=1500 — inside the window, held
    advance(500); // t=2000 — the window closes on what frames 2 and 3 asked for
    assert.deepEqual(bumpsAt, [0, 2000]);

    advance(250);
    bump(); // frame 4, t=2250 — inside the second window, held
    advance(750);
    bump(); // frame 5, t=3000 — the LAST frame, also held
    assert.deepEqual(
      bumpsAt,
      [0, 2000],
      "no bump may land inside the two-second window",
    );

    advance(1000); // t=4000 — the trailing bump the last frame is owed
    assert.deepEqual(bumpsAt, [0, 2000, 4000]);

    advance(10_000);
    assert.deepEqual(bumpsAt, [0, 2000, 4000], "the clock alone bumps nothing");
    bump.cancel();
  });
});

test("the last checkpoint of a burst is never the one dropped", () => {
  onFakeClock(() => {
    let bumps = 0;
    const bump = throttleTrailing(() => {
      bumps += 1;
    }, 2000);

    for (let i = 0; i < 50; i += 1) {
      bump();
      mock.timers.tick(20);
    }
    const duringBurst = bumps;
    mock.timers.tick(2000);
    assert.equal(
      bumps,
      duringBurst + 1,
      "the trailing edge owes exactly one more bump after the burst",
    );
    bump.cancel();
  });
});

test("bumps are never closer together than the interval", () => {
  onFakeClock(() => {
    const bumpsAt: number[] = [];
    const { now, advance } = steppedClock();
    const bump = throttleTrailing(() => {
      bumpsAt.push(now());
    }, 2000);

    // A checkpoint every 300ms for eighteen seconds — a plausible busy run,
    // and an arrival rate that shares no factor with the window boundary.
    for (let i = 0; i < 60; i += 1) {
      bump();
      advance(300);
    }
    advance(2000);

    assert.ok(bumpsAt.length > 1);
    for (let i = 1; i < bumpsAt.length; i += 1) {
      assert.ok(
        bumpsAt[i] - bumpsAt[i - 1] >= 2000,
        `bumps ${i - 1} and ${i} are only ${bumpsAt[i] - bumpsAt[i - 1]}ms apart`,
      );
    }
    bump.cancel();
  });
});

test("cancel drops the pending trailing bump, so an unmount stays quiet", () => {
  onFakeClock(() => {
    let bumps = 0;
    const bump = throttleTrailing(() => {
      bumps += 1;
    }, 2000);

    bump();
    bump(); // pending
    assert.equal(bumps, 1);
    bump.cancel();
    mock.timers.tick(10_000);
    assert.equal(bumps, 1, "a cancelled throttle must not fire after teardown");
  });
});
