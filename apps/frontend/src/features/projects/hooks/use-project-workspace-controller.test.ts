import assert from "node:assert/strict";
import test from "node:test";
import {
  initialWorkspaceFocusPane,
  workspaceRemountKey,
} from "./use-project-workspace-controller";

test("an empty Gallery gives the conversation the workspace by default", () => {
  assert.equal(initialWorkspaceFocusPane(0), "conversation");
  assert.equal(initialWorkspaceFocusPane(2), "split");
});

test("an explicit Gallery route still opens the requested workspace", () => {
  assert.equal(initialWorkspaceFocusPane(0, "artifacts"), "artifacts");
});

test("a chats-path param change flips the workspace remount key (sidebar-click regression, Phase R)", () => {
  // App Router preserves client state across dynamic-param navigation of the
  // same route; this key is the ONLY mechanism that makes a URL-driven thread
  // change take effect. It must differ whenever the thread differs.
  assert.notEqual(
    workspaceRemountKey("w1", { threadId: "t1" }),
    workspaceRemountKey("w1", { threadId: "t2" }),
  );
  assert.equal(
    workspaceRemountKey("w1", { threadId: "t1" }),
    workspaceRemountKey("w1", { threadId: "t1" }),
  );
});

test("the remount key tracks handoff identity exactly as the legacy route did", () => {
  assert.notEqual(
    workspaceRemountKey("w1", { handoffId: "h1", threadId: "t1" }),
    workspaceRemountKey("w1", { threadId: "t1" }),
  );
  assert.equal(
    workspaceRemountKey("w1", { threadId: "t1" }),
    "w1:t1:",
  );
});
