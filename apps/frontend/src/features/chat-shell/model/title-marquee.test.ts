import assert from "node:assert/strict";
import test from "node:test";
import { TITLE_MARQUEE_GAP_PX, TITLE_MARQUEE_PX_PER_SECOND, titleMarqueePlan } from "./title-marquee";

test("a title that fits does not scroll", () => {
  assert.equal(titleMarqueePlan({ textWidth: 120, boxWidth: 120 }), null);
  assert.equal(titleMarqueePlan({ textWidth: 80, boxWidth: 120 }), null);
});

test("a cut title scrolls one whole loop: the name plus the gap, so its first letter ends where it began", () => {
  const plan = titleMarqueePlan({ textWidth: 300, boxWidth: 120 });
  assert.ok(plan);
  assert.equal(plan.shiftPx, 300 + TITLE_MARQUEE_GAP_PX);
  assert.equal(plan.durationMs, Math.round(((300 + TITLE_MARQUEE_GAP_PX) / TITLE_MARQUEE_PX_PER_SECOND) * 1000));
});

test("a longer name scrolls for longer at the same speed", () => {
  const short = titleMarqueePlan({ textWidth: 200, boxWidth: 120 });
  const long = titleMarqueePlan({ textWidth: 400, boxWidth: 120 });
  assert.ok(short && long);
  assert.ok(long.durationMs > short.durationMs);
  assert.equal(
    Math.round(long.shiftPx / (long.durationMs / 1000)),
    Math.round(short.shiftPx / (short.durationMs / 1000)),
  );
});

test("sub-pixel rounding never starts a scroll for a title that really fits", () => {
  assert.equal(titleMarqueePlan({ textWidth: 120.4, boxWidth: 120 }), null);
});
