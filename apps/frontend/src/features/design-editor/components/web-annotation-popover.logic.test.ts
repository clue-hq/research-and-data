import assert from "node:assert/strict";
import test from "node:test";

import { computePopoverPosition } from "./web-annotation-popover.logic";

/** The canvas iframe: 1000px wide, starting 100px in — so its right edge is at
 * 1100, well inside the 1400px window. Every case below turns on THAT edge,
 * not the window's: a card that flipped at the window edge would land on the
 * inspector pane beside the canvas. */
const iframe = { left: 100, top: 50, width: 1000, height: 800 };
const box = { width: 320, height: 180 };
const viewport = { width: 1400, height: 900 };

test("the box sits to the right of the element when it fits inside the frame", () => {
  const el = { x: 200, y: 100, width: 300, height: 60 };
  assert.deepEqual(computePopoverPosition(iframe, el, box, viewport), {
    left: 100 + 200 + 300 + 12,
    top: 50 + 100,
  });
});

test("an element at the frame's right edge flips the box LEFT, still inside the frame", () => {
  // Right side would need 1102+320; the frame ends at 1100. The left side has
  // room (468 >= the frame's own left edge of 100), so that is where it goes.
  const el = { x: 700, y: 100, width: 290, height: 60 };
  assert.deepEqual(computePopoverPosition(iframe, el, box, viewport), {
    left: 100 + 700 - 320 - 12,
    top: 150,
  });
});

test("a full-width element leaves no side free, so the box drops BELOW it, clamped inside the frame", () => {
  const el = { x: 0, y: 100, width: 1000, height: 60 };
  assert.deepEqual(computePopoverPosition(iframe, el, box, viewport), {
    left: 100,
    top: 50 + 100 + 60 + 12,
  });
});

test("the viewport clamp runs last, so a box anchored near the bottom still lands whole", () => {
  const el = { x: 0, y: 780, width: 1000, height: 60 };
  assert.deepEqual(computePopoverPosition(iframe, el, box, viewport), {
    left: 100,
    top: 900 - 180,
  });
});
