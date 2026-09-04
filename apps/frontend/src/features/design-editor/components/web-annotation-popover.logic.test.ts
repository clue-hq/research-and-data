import assert from "node:assert/strict";
import test from "node:test";

import { computePopoverPosition } from "./web-annotation-popover.logic";

test("the box sits to the right of the element inside the viewport, else flips left", () => {
  const iframe = { left: 100, top: 50, width: 1000, height: 800 };
  const el = { x: 200, y: 100, width: 300, height: 60 };
  assert.deepEqual(
    computePopoverPosition(
      iframe,
      el,
      { width: 320, height: 180 },
      { width: 1400, height: 900 },
    ),
    { left: 100 + 200 + 300 + 12, top: 50 + 100 },
  );
  const farRight = { x: 800, y: 100, width: 190, height: 60 };
  assert.deepEqual(
    computePopoverPosition(
      iframe,
      farRight,
      { width: 320, height: 180 },
      { width: 1400, height: 900 },
    ),
    { left: 100 + 800 - 320 - 12, top: 150 },
  );
});
