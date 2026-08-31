import assert from "node:assert/strict";
import test from "node:test";
import { CHAT_SESSION_ACTIONS } from "./chat-session-actions";

test("chat session actions expose only backend-owned mutations", () => {
  assert.deepEqual(CHAT_SESSION_ACTIONS, ["archive", "delete"]);
});
