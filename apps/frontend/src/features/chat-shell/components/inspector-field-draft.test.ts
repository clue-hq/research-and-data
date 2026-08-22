import test from "node:test";
import assert from "node:assert/strict";
import { fieldCommit, fieldDisplay } from "./inspector-field-draft";

test("display prefers the draft while one exists", () => {
  assert.equal(fieldDisplay("10", "32"), "10");
  assert.equal(fieldDisplay("", "32"), ""); // an emptied box shows empty
  assert.equal(fieldDisplay(null, "32"), "32"); // no draft → the document value
});

test("a commit is the draft, unless there is nothing new to say", () => {
  assert.equal(fieldCommit("96", "32"), "96");
  assert.equal(fieldCommit(null, "32"), null); // never typed → no write
  assert.equal(fieldCommit("32", "32"), null); // A27 structural: same value → no write
  assert.equal(fieldCommit("", "32"), ""); // an explicit clear IS a commit —
  // the write adapter decides what an empty string means per row (radius: no
  // write; alt text: clear), exactly as it does today.
});
