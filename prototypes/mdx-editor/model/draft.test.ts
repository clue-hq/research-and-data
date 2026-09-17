import assert from "node:assert/strict";
import test from "node:test";
import { bodyAfterChange, canSaveDraft } from "./draft";

test("normalization and undo to the initial library state preserve original bytes", () => {
  const raw = "# Title\n\n-  First\n";
  const normalized = "# Title\n\n* First\n";
  assert.equal(bodyAfterChange(raw, normalized, normalized), raw);
  assert.equal(bodyAfterChange(raw, normalized, normalized + "\nSecond"), normalized + "\nSecond");
  assert.equal(bodyAfterChange(raw, null, raw), raw);
});

test("untouched, read-only and failed imports cannot be saved", () => {
  assert.equal(canSaveDraft("same", "same", false, false), false);
  assert.equal(canSaveDraft("before", "after", true, false), false);
  assert.equal(canSaveDraft("original", "", false, true), false);
  assert.equal(canSaveDraft("before", "after", false, false), true);
});
