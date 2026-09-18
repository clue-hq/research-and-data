import assert from "node:assert/strict";
import test from "node:test";
import {
  AuthenticatedSessionSchema,
  roleLabel,
  SessionMembershipSchema,
  RequestPrincipalSchema,
  resolveWorkspaceMembership,
} from "./session";

test("session wire schema contains only Clue-owned identity values", () => {
  const parsed = AuthenticatedSessionSchema.parse({
    user_id: "usr_123",
    memberships: [
      {
        membership_id: "wsm_123",
        workspace_id: "ws_123",
        workspace_name: "Insight Health",
        role_key: "operator",
        permissions: ["thread.read"],
      },
    ],
    has_inactive_memberships: false,
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

test("a missing or stale workspace cookie requires an explicit selection", () => {
  const session = AuthenticatedSessionSchema.parse({
    user_id: "usr_123",
    memberships: [
      {
        membership_id: "wsm_active",
        workspace_id: "ws_active",
        workspace_name: "Active workspace",
        role_key: "viewer",
        permissions: ["project.read"],
      },
    ],
    has_inactive_memberships: true,
  });

  assert.equal(resolveWorkspaceMembership(session, null), null);
  assert.equal(resolveWorkspaceMembership(session, "ws_revoked"), null);
});

test("multiple memberships require an explicit workspace selection", () => {
  const session = AuthenticatedSessionSchema.parse({
    user_id: "usr_123",
    has_inactive_memberships: false,
    memberships: [
      {
        membership_id: "wsm_one",
        workspace_id: "ws_one",
        workspace_name: "Workspace one",
        role_key: "viewer",
        permissions: ["project.read"],
      },
      {
        membership_id: "wsm_two",
        workspace_id: "ws_two",
        workspace_name: "Workspace two",
        role_key: "operator",
        permissions: ["project.read"],
      },
    ],
  });

  assert.equal(resolveWorkspaceMembership(session, null), null);
  assert.equal(
    resolveWorkspaceMembership(session, "ws_two")?.workspace_id,
    "ws_two",
  );
});

test("a pinned local instance ignores another tab's selected workspace", () => {
  const session = AuthenticatedSessionSchema.parse({
    user_id: "usr_owner",
    has_inactive_memberships: false,
    memberships: [
      { membership_id: "wsm_aws", workspace_id: "ws_aws", workspace_name: "AWS", role_key: "owner", permissions: [] },
      { membership_id: "wsm_conduit", workspace_id: "ws_conduit", workspace_name: "Conduit", role_key: "owner", permissions: [] },
    ],
  });
  for (const cookie of [null, "ws_aws", "ws_conduit", "ws_stale"]) {
    assert.equal(resolveWorkspaceMembership(session, cookie, "ws_aws")?.workspace_id, "ws_aws");
  }
});

test("a local pin never grants missing membership or falls back to another brand", () => {
  const session = AuthenticatedSessionSchema.parse({
    user_id: "usr_owner",
    has_inactive_memberships: true,
    memberships: [
      { membership_id: "wsm_conduit", workspace_id: "ws_conduit", workspace_name: "Conduit", role_key: "owner", permissions: [] },
    ],
  });
  assert.equal(resolveWorkspaceMembership(session, "ws_conduit", "ws_revoked"), null);
});

test("a membership carries the workspace's display name, and must", () => {
  const membership = {
    membership_id: "wsm_123",
    workspace_id: "ws_123",
    role_key: "owner",
    permissions: [],
  };
  assert.equal(
    SessionMembershipSchema.safeParse(membership).success,
    false,
    "a membership without a display name is not a session the UI can render",
  );
  const named = SessionMembershipSchema.parse({
    ...membership,
    workspace_name: "Insight Health",
  });
  assert.equal(named.workspace_name, "Insight Health");
  assert.equal(
    SessionMembershipSchema.safeParse({ ...membership, workspace_name: "" }).success,
    false,
    "an empty name would render as nothing at all",
  );
});

test("a role reads as a word, and lives where the server can call it", () => {
  // The protected layout (a server component) labels each membership's role, so
  // this must NOT live in the switcher's "use client" module: Next refuses to
  // call a client module's function from the server.
  assert.equal(roleLabel("owner"), "Owner");
  assert.equal(roleLabel("operator"), "Operator");
  assert.equal(roleLabel(""), "");
});
