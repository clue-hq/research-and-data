import assert from "node:assert/strict";
import test from "node:test";
import {
  patchSettingsProfile,
  patchSettingsWorkspace,
  changeSettingsMember,
  inviteSettingsMembers,
} from "./settings.actions";
import { getSettingsProfile } from "./profile.repository";
import { getSettingsMembers } from "./members.repository";
import { shellProfile } from "../model/profile";
import {
  memberJoinedLabel,
  memberRoleLabel,
  invitationSummary,
} from "../model/members";

const profile = {
  user_id: "u_test",
  full_name: "Ada Lovelace",
  first_name: "Ada",
  last_name: "Lovelace",
  display_name: null,
  email: "ada@example.com",
};

test("display-name clearing uses null and the shared shell falls back to the full name", async () => {
  let requestBody: unknown;
  const result = await patchSettingsProfile(
    { display_name: null },
    async (input, init) => {
      assert.equal(input, "/api/clue/frontend/v1/settings/profile");
      assert.equal(init?.method, "PATCH");
      requestBody = JSON.parse(String(init?.body));
      return Response.json(profile);
    },
  );
  assert.deepEqual(requestBody, { display_name: null });
  assert.equal(shellProfile(result).displayName, "Ada Lovelace");
  assert.equal(shellProfile({ ...result, display_name: "Ada" }).initials, "A");
});

test("live reads reject malformed or failed payloads instead of substituting fixture people", async () => {
  await assert.rejects(
    getSettingsProfile(async () => Response.json({})),
    /Invalid/,
  );
  await assert.rejects(
    getSettingsMembers(async () =>
      Response.json(
        {
          error: {
            code: "WORKSPACE_FORBIDDEN",
            message: "Access removed",
            requestId: "r_test",
          },
        },
        { status: 403 },
      ),
    ),
    /Access removed/,
  );
});

test("workspace changes submit only the name and preserve typed refusals", async () => {
  await assert.rejects(
    patchSettingsWorkspace("Example", async (_input, init) => {
      assert.deepEqual(JSON.parse(String(init?.body)), { name: "Example" });
      return Response.json(
        {
          error: {
            code: "PERMISSION_REQUIRED",
            message: "Administration permission required",
            requestId: "r_test",
          },
        },
        { status: 403 },
      );
    }),
    /Administration permission required/,
  );
});

test("member mutations use the correct scoped action and validate success", async () => {
  const seen: [string, string, unknown][] = [];
  const request: typeof fetch = async (input, init) => {
    seen.push([
      String(input),
      String(init?.method),
      init?.body ? JSON.parse(String(init.body)) : null,
    ]);
    return Response.json({ ok: true });
  };
  await changeSettingsMember("m/a", "role", "admin", request);
  await changeSettingsMember("m_test", "readmit", "operator", request);
  await changeSettingsMember("inv_test", "revoke", "operator", request);
  assert.deepEqual(seen, [
    [
      "/api/clue/frontend/v1/settings/members/m%2Fa",
      "PATCH",
      { role: "admin" },
    ],
    [
      "/api/clue/frontend/v1/settings/members/m_test/readmit",
      "POST",
      { role: "operator" },
    ],
    [
      "/api/clue/frontend/v1/settings/members/invitations/inv_test",
      "DELETE",
      null,
    ],
  ]);
});

test("partial invitation outcomes and removed rows remain visible", async () => {
  const result = await inviteSettingsMembers(
    ["a@example.com", "bad"],
    "operator",
    async () =>
      Response.json({
        outcomes: [
          { email: "a@example.com", outcome: "sent" },
          { email: "bad", outcome: "invalid" },
        ],
      }),
  );
  assert.match(invitationSummary(result), /invalid/);
  assert.match(invitationSummary(result), /sent/);
  assert.equal(memberRoleLabel("owner"), "Admin");
  assert.equal(memberRoleLabel("viewer"), "Member");
  assert.equal(
    memberJoinedLabel({
      kind: "member",
      id: "m",
      name: null,
      email: null,
      role_key: "operator",
      state: "removed",
      joined_on: "2026-09-15",
      is_self: false,
    }),
    "Removed",
  );
});
