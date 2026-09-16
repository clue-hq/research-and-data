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

const researchField = {
  key: "account.uses_crm", label: "Uses CRM", description: "Find their CRM.",
  origin: "workspace", created_by: "Ada", created_at: "2026-09-16T12:00:00+00:00",
};

test("research field repositories validate scope and mutations preserve server keys", async () => {
  const { getSettingsResearchFields } = await import("./research-fields.repository");
  const { createSettingsResearchField, patchSettingsResearchField, retireSettingsResearchField } = await import("./settings.actions");
  const fields = await getSettingsResearchFields("accounts", async (input) => {
    assert.equal(input, "/frontend/v1/settings/research-fields?entity=accounts");
    return Response.json({ entity: "accounts", rows: [researchField] });
  });
  assert.equal(fields.rows[0].key, researchField.key);
  await assert.rejects(getSettingsResearchFields("contacts", async () => Response.json({ entity: "accounts", rows: [] })), /mismatch/);
  await assert.rejects(getSettingsResearchFields("accounts", async () => Response.json({ entity: "accounts", rows: [{}] })), /Invalid/);
  const seen: unknown[] = [];
  const request: typeof fetch = async (input, init) => {
    seen.push([input, init?.method, init?.body ? JSON.parse(String(init.body)) : null]);
    return Response.json(init?.method === "DELETE" ? { ok: true } : researchField);
  };
  await createSettingsResearchField({ entity: "accounts", label: "Uses CRM", description: "Find their CRM." }, request);
  await patchSettingsResearchField(researchField.key, { description: "Find cited CRM evidence." }, request);
  await retireSettingsResearchField(researchField.key, request);
  assert.deepEqual(seen, [
    ["/api/clue/frontend/v1/settings/research-fields", "POST", { entity: "accounts", label: "Uses CRM", description: "Find their CRM." }],
    ["/api/clue/frontend/v1/settings/research-fields/account.uses_crm", "PATCH", { description: "Find cited CRM evidence." }],
    ["/api/clue/frontend/v1/settings/research-fields/account.uses_crm", "DELETE", null],
  ]);
  await assert.rejects(createSettingsResearchField({ entity: "accounts", label: "Uses CRM", description: "Find their CRM." }, async () => Response.json({ error: { code: "KEY_TAKEN", message: "This name is reserved" } }, { status: 409 })), /reserved/);
});
