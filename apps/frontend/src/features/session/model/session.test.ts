import assert from "node:assert/strict";
import test from "node:test";
import {
  AuthenticatedSessionSchema,
  RequestPrincipalSchema,
} from "./session";

test("session wire schema contains only Clue-owned identity values", () => {
  const parsed = AuthenticatedSessionSchema.parse({
    user_id: "usr_123",
    memberships: [
      {
        membership_id: "wsm_123",
        workspace_id: "ws_123",
        role_key: "operator",
        permissions: ["thread.read"],
      },
    ],
  });
  assert.equal(parsed.user_id, "usr_123");
  assert.equal(parsed.memberships[0]?.workspace_id, "ws_123");
});

test("principal wire schema refuses provider fields", () => {
  const parsed = RequestPrincipalSchema.safeParse({
    user_id: "usr_123",
    membership_id: "wsm_123",
    workspace_id: "ws_123",
    role_key: "viewer",
    permissions: ["project.read"],
    provider_subject: "clerk-user",
  });
  assert.equal(parsed.success, false);
});
