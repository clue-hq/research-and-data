import assert from "node:assert/strict";
import test from "node:test";
import { ClueApiError } from "@/features/accounts/data/clue-api-error";
import {
  fixtureCrmSettingsRepository,
  httpCrmSettingsRepository,
} from "./crm-settings.repository";
import { crmIntegrationFixture } from "./crm-settings.fixtures";
import { crmSettingsFixtureSelection, readCrmIntegration } from "./crm-settings.server";

interface Call {
  url: string;
  method: string;
  body: unknown;
}

function fakeFetch(answer: (call: Call) => Response) {
  const calls: Call[] = [];
  const request = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const call = {
      url: String(input),
      method: init?.method ?? "GET",
      body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined,
    };
    calls.push(call);
    return answer(call);
  }) as typeof fetch;
  return { calls, request };
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

test("every Settings route goes through the same-origin BFF with the backend's shapes", async () => {
  const integration = crmIntegrationFixture("ready", "salesforce");
  const { calls, request } = fakeFetch((call) => {
    if (call.url.endsWith("/crm/integration")) return json(integration);
    if (call.url.endsWith("/crm/connect-request"))
      return json({ requestId: "0b9d5f3e-7d6a-4a8e-9f0b-3c1d2e4f5a6b" });
    if (call.url.endsWith("/crm/disconnect")) return json({ outcome: "disconnected" });
    if (call.url.includes("/crm/permissions/")) return json({ outcome: "already_revoked" });
    if (call.url.endsWith("/crm/overwrites")) return json({ overwrites: "follow_grants" });
    return json({}, 500);
  });
  const repo = httpCrmSettingsRepository(request);

  assert.equal((await repo.getIntegration()).research.state, "ready");
  assert.equal(await repo.requestConnect("switch"), "0b9d5f3e-7d6a-4a8e-9f0b-3c1d2e4f5a6b");
  await repo.disconnect();
  assert.equal(await repo.revokePermission("g/1"), "already_revoked");
  assert.equal(await repo.setOverwrites("follow_grants"), "follow_grants");

  assert.deepEqual(calls, [
    { url: "/api/clue/frontend/v1/crm/integration", method: "GET", body: undefined },
    { url: "/api/clue/frontend/v1/crm/connect-request", method: "POST", body: { mode: "switch" } },
    { url: "/api/clue/frontend/v1/crm/disconnect", method: "POST", body: undefined },
    { url: "/api/clue/frontend/v1/crm/permissions/g%2F1/revoke", method: "POST", body: undefined },
    { url: "/api/clue/frontend/v1/crm/overwrites", method: "PUT", body: { mode: "follow_grants" } },
  ]);
});

test("a refusal is read from the backend's {error: {code, message}} envelope", async () => {
  const { request } = fakeFetch(() =>
    json(
      { error: { code: "crm_not_connected", message: "No CRM is connected.", requestId: "req_1" } },
      409,
    ),
  );
  await assert.rejects(httpCrmSettingsRepository(request).disconnect(), (error: unknown) => {
    assert.ok(error instanceof ClueApiError);
    assert.equal(error.code, "crm_not_connected");
    assert.equal(error.status, 409);
    assert.equal(error.requestId, "req_1");
    return true;
  });
});

test("a refusal without an envelope still throws a typed error", async () => {
  const { request } = fakeFetch(() => new Response("<html>bad gateway</html>", { status: 502 }));
  await assert.rejects(httpCrmSettingsRepository(request).getIntegration(), (error: unknown) => {
    assert.ok(error instanceof ClueApiError);
    assert.equal(error.code, "HTTP_502");
    return true;
  });
});

test("a payload the schema refuses is not served", async () => {
  const { request } = fakeFetch(() => json({ connection: null }));
  await assert.rejects(httpCrmSettingsRepository(request).getIntegration());
});

test("the fixture adapter answers like the backend and keeps its own state", async () => {
  const repo = fixtureCrmSettingsRepository(crmIntegrationFixture("ready", "hubspot"));
  const before = await repo.getIntegration();
  const grant = before.permissions[0];
  assert.ok(grant);

  assert.equal(await repo.revokePermission(grant.grantId), "revoked");
  assert.equal(await repo.revokePermission(grant.grantId), "already_revoked");
  assert.equal((await repo.getIntegration()).permissions.length, before.permissions.length - 1);

  assert.equal(await repo.setOverwrites("follow_grants"), "follow_grants");
  assert.equal((await repo.getIntegration()).overwrites, "follow_grants");

  assert.match(await repo.requestConnect("reconnect"), /^[0-9a-f-]{36}$/);

  await repo.disconnect();
  const after = await repo.getIntegration();
  assert.equal(after.connection?.status, "disconnected");
  assert.equal(after.research.state, "not_connected");
  assert.deepEqual(after.permissions, []);
  await assert.rejects(repo.disconnect(), (error: unknown) => {
    assert.ok(error instanceof ClueApiError);
    assert.equal(error.code, "crm_not_connected");
    return true;
  });
  await assert.rejects(repo.revokePermission("nope"), (error: unknown) => {
    assert.ok(error instanceof ClueApiError);
    assert.equal(error.code, "crm_permission_not_found");
    return true;
  });
});

test("a member's fixture refuses the manager-only actions like the backend does", async () => {
  const integration = { ...crmIntegrationFixture("ready", "hubspot"), canManage: false };
  const repo = fixtureCrmSettingsRepository(integration);
  await assert.rejects(repo.disconnect(), (error: unknown) => {
    assert.ok(error instanceof ClueApiError);
    assert.equal(error.code, "PERMISSION_REQUIRED");
    assert.equal(error.status, 403);
    return true;
  });
  const grant = integration.permissions[0];
  assert.ok(grant);
  assert.equal(await repo.revokePermission(grant.grantId), "revoked");
});

test("the server read uses the authenticated read seam", async () => {
  const paths: string[] = [];
  const integration = await readCrmIntegration(async (path) => {
    paths.push(path);
    return json(crmIntegrationFixture("preparing", "hubspot"));
  });
  assert.equal(integration.research.state, "preparing");
  assert.deepEqual(paths, ["/frontend/v1/crm/integration"]);
});

test("the fixture switch is explicit: provider:state, anything else is live", () => {
  assert.deepEqual(crmSettingsFixtureSelection("salesforce:permission_needed"), {
    provider: "salesforce",
    state: "permission_needed",
  });
  assert.equal(crmSettingsFixtureSelection(undefined), null);
  assert.equal(crmSettingsFixtureSelection(""), null);
  assert.equal(crmSettingsFixtureSelection("hubspot"), null);
  assert.equal(crmSettingsFixtureSelection("pipedrive:ready"), null);
  assert.equal(crmSettingsFixtureSelection("hubspot:done"), null);
});

test("with the switch set the server read serves that fixture without calling the backend", async () => {
  const previous = process.env.CLUE_CRM_SETTINGS_FIXTURE;
  process.env.CLUE_CRM_SETTINGS_FIXTURE = "salesforce:needs_attention";
  try {
    const integration = await readCrmIntegration(async () => {
      throw new Error("the backend must not be called");
    });
    assert.equal(integration.connection?.provider, "salesforce");
    assert.equal(integration.research.state, "needs_attention");
  } finally {
    if (previous === undefined) delete process.env.CLUE_CRM_SETTINGS_FIXTURE;
    else process.env.CLUE_CRM_SETTINGS_FIXTURE = previous;
  }
});
