import assert from "node:assert/strict";
import test from "node:test";
import { applyLiftedChoice } from "./use-artifact-toolbar-controller";

// The toolbar's menus are LIFTED the same way: when the caller passes a change
// handler the choice is REPORTED and never stored here (the caller owns the
// value and feeds it back), and when it does not the local fallback stores it.
// F5 task 18 adds the page menu to that family (device, zoom, page), so the
// rule is tested once, on the dispatcher all three call.

test("a lifted choice is reported to the caller and never stored locally", () => {
  const reported: string[] = [];
  const stored: string[] = [];

  applyLiftedChoice(
    "page_pricing",
    (value: string) => reported.push(value),
    (value: string) => stored.push(value),
  );

  assert.deepEqual(reported, ["page_pricing"]);
  assert.deepEqual(stored, []);
});

test("without a caller handler the choice falls back to local state", () => {
  const stored: string[] = [];

  applyLiftedChoice("page_pricing", undefined, (value: string) =>
    stored.push(value),
  );

  assert.deepEqual(stored, ["page_pricing"]);
});

test("the device menu lifts by the same rule", () => {
  const reported: string[] = [];
  const stored: string[] = [];

  applyLiftedChoice("Mobile" as const, (value) => reported.push(value), (value) =>
    stored.push(value),
  );
  applyLiftedChoice("Tablet" as const, undefined, (value) => stored.push(value));

  assert.deepEqual(reported, ["Mobile"]);
  assert.deepEqual(stored, ["Tablet"]);
});
