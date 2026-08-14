import assert from "node:assert/strict";
import test from "node:test";
import {
  handleProvisionRequest,
  type ProvisionHandlerDependencies,
  type ProvisionLogFields,
} from "./provision-handler";

const BODY = JSON.stringify({
  first_name: "Onboarding",
  last_name: "Test",
  job_role: "Founder",
  company_name: "Insight Health",
  company_website: "https://insighthealth.ai",
});

function request(headers: HeadersInit = {}): Request {
  return new Request("http://localhost:3000/api/onboarding/provision", {
    method: "POST",
    headers: {
      Origin: "http://localhost:3000",
      Cookie: "__session=browser-secret",
      Authorization: "Bearer browser-controlled",
      "Content-Type": "application/json",
      ...headers,
    },
    body: BODY,
  });
}

function dependencies(
  overrides: Partial<ProvisionHandlerDependencies> = {},
): ProvisionHandlerDependencies {
  return {
    authenticationEnabled: true,
    originAllowed: true,
    async providerToken() {
      return "server-session-token";
    },
    backendBaseUrl: "http://127.0.0.1:8000",
    requestId: "request-123",
    ...overrides,
  };
}

test("provision handler rejects a forbidden origin before reading provider credentials", async () => {
  let tokenCalls = 0;
  const logs: ProvisionLogFields[] = [];
  const response = await handleProvisionRequest(
    request({ Origin: "http://127.0.0.1:3000" }),
    dependencies({
      originAllowed: false,
      async providerToken() {
        tokenCalls += 1;
        return "must-not-be-read";
      },
      log(_event, fields) {
        logs.push(fields);
      },
    }),
  );

  assert.equal(response.status, 403);
  assert.equal(tokenCalls, 0);
  assert.equal(response.headers.get("x-request-id"), "request-123");
  assert.deepEqual(await response.json(), {
    error: {
      code: "REQUEST_ORIGIN_FORBIDDEN",
      message: "Mutation origin is not allowed",
      requestId: "request-123",
    },
  });
  assert.deepEqual(logs, [
    { request_id: "request-123", outcome: "origin_forbidden", status: 403 },
  ]);
});

test("provision handler refuses a missing server-side Clerk session", async () => {
  const response = await handleProvisionRequest(
    request(),
    dependencies({
      async providerToken() {
        return null;
      },
    }),
  );

  assert.equal(response.status, 401);
  assert.equal((await response.json()).error.code, "AUTHENTICATION_REQUIRED");
});

test("provision handler forwards only its server token, body, and correlated request id", async () => {
  let capturedUrl = "";
  let capturedInit: RequestInit | undefined;
  const logs: ProvisionLogFields[] = [];
  const fakeFetch = (async (input: URL | RequestInfo, init?: RequestInit) => {
    capturedUrl = String(input);
    capturedInit = init;
    return Response.json(
      {
        user_id: "usr_1",
        workspace_id: "ws_1",
        created: true,
      },
      { status: 200, headers: { "X-Request-Id": "request-123" } },
    );
  }) as typeof fetch;

  const response = await handleProvisionRequest(
    request(),
    dependencies({
      fetch: fakeFetch,
      log(_event, fields) {
        logs.push(fields);
      },
    }),
  );

  assert.equal(response.status, 200);
  assert.equal(response.headers.get("x-request-id"), "request-123");
  assert.equal(capturedUrl, "http://127.0.0.1:8000/auth/v1/provision");
  const headers = new Headers(capturedInit?.headers);
  assert.equal(headers.get("authorization"), "Bearer server-session-token");
  assert.equal(headers.get("x-request-id"), "request-123");
  assert.equal(headers.get("cookie"), null);
  assert.equal(await new Response(capturedInit?.body).text(), BODY);
  assert.deepEqual(logs, [
    { request_id: "request-123", outcome: "forwarded", status: 200 },
  ]);
});
