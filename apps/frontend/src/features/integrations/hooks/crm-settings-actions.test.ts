import assert from "node:assert/strict";
import test from "node:test";
import { ClueApiError } from "@/features/accounts/data/clue-api-error";
import { crmIntegrationFixture, withFixtureVariants } from "../data/crm-settings.fixtures";
import {
  CrmWorkspaceChangedError,
  fixtureCrmSettingsRepository,
} from "../data/crm-settings.repository";
import { runCrmSettingsAction } from "./crm-settings-actions";

function harness() {
  const calls: string[] = [];
  return {
    calls,
    deps: {
      refresh: () => calls.push("refresh"),
      reload: () => calls.push("reload"),
    },
  };
}

function refusal(code: string, status: number) {
  return new ClueApiError("refused", { code, status, requestId: "req_1" });
}

test("a finished action refreshes the page's data and reports no message", async () => {
  const { calls, deps } = harness();
  const repository = fixtureCrmSettingsRepository(crmIntegrationFixture("ready", "hubspot"));
  const outcome = await runCrmSettingsAction(deps, () => repository.setOverwrites("follow_grants"));
  assert.deepEqual(outcome, { ok: true });
  assert.deepEqual(calls, ["refresh"]);
  assert.equal((await repository.getIntegration()).overwrites, "follow_grants");
});

test("a member's revoke goes through, while the manager-only actions are refused in words", async () => {
  const integration = withFixtureVariants(crmIntegrationFixture("ready", "hubspot"), ["member"]);
  const repository = fixtureCrmSettingsRepository(integration);
  const { calls, deps } = harness();
  assert.deepEqual(
    await runCrmSettingsAction(deps, () => repository.revokePermission(integration.permissions[0].grantId)),
    { ok: true },
  );
  assert.deepEqual(await runCrmSettingsAction(deps, () => repository.disconnect()), {
    ok: false,
    message: "Only a workspace owner or admin can change this.",
  });
  assert.deepEqual(calls, ["refresh"]);
});

test("a workspace switched in another tab reloads the page and shows nothing", async () => {
  const { calls, deps } = harness();
  const outcome = await runCrmSettingsAction(deps, async () => {
    throw new CrmWorkspaceChangedError(refusal("WORKSPACE_CHANGED", 409));
  });
  assert.deepEqual(outcome, { ok: false, message: null });
  assert.deepEqual(calls, ["reload"]);
});

test("each backend refusal reads as a plain sentence", async () => {
  const { calls, deps } = harness();
  const cases: [Error, string][] = [
    [refusal("crm_not_connected", 409), "The CRM is no longer connected. Reload the page to see its current state."],
    [refusal("crm_permission_not_found", 404), "This permission no longer exists. Reload the page to see the current list."],
    [refusal("PERMISSION_REQUIRED", 403), "Only a workspace owner or admin can change this."],
    [refusal("HTTP_ERROR", 500), "Something went wrong. Please try again."],
    [new TypeError("Failed to fetch"), "Something went wrong. Please try again."],
  ];
  for (const [error, message] of cases) {
    assert.deepEqual(
      await runCrmSettingsAction(deps, async () => {
        throw error;
      }),
      { ok: false, message },
    );
  }
  assert.deepEqual(calls, []);
});
