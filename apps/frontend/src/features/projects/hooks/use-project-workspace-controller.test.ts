import assert from "node:assert/strict";
import test from "node:test";
import { initialWorkspaceFocusPane } from "./use-project-workspace-controller";

test("an empty Gallery gives the conversation the workspace by default", () => {
  assert.equal(initialWorkspaceFocusPane(0), "conversation");
  assert.equal(initialWorkspaceFocusPane(2), "split");
});

test("an explicit Gallery route still opens the requested workspace", () => {
  assert.equal(initialWorkspaceFocusPane(0, "artifacts"), "artifacts");
});
