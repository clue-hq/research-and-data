import assert from "node:assert/strict";
import test from "node:test";
import { ARTIFACT_ACTIONS } from "./artifact-actions";

test("artifact actions preserve the reviewed menu contract", () => {
  assert.deepEqual(ARTIFACT_ACTIONS, [
    "rename",
    "duplicate",
    "undo",
    "redo",
    "versions",
    "archive",
    "delete",
  ]);
});
