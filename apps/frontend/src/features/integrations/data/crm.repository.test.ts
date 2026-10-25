import assert from "node:assert/strict";
import test from "node:test";
import { CrmConnectError } from "../model/crm";
import { crmErrorCode, fetchCrmProposal, requestConnectLink } from "./crm.repository";

const REQUEST = "0b9d5f3e-7d6a-4a8e-9f0b-3c1d2e4f5a6b";

const refusal = (status: number, code: string) =>
  (async () =>
    new Response(JSON.stringify({ error: { code, message: "refused", requestId: "req_1" } }), {
      status,
      headers: { "Content-Type": "application/json" },
    })) as typeof fetch;

test("the refusal code is read from the backend's {error: {code}} envelope", async () => {
  const response = await refusal(409, "connect_request_closed")("/x");
  assert.equal(await crmErrorCode(response), "connect_request_closed");
});

test("a body that is not the envelope falls back to the HTTP status", async () => {
  assert.equal(await crmErrorCode(new Response("<html/>", { status: 502 })), "HTTP_502");
  assert.equal(
    await crmErrorCode(new Response(JSON.stringify({ detail: { code: "x" } }), { status: 400 })),
    "HTTP_400",
  );
});

test("a closed connect card is told so (the code is no longer lost)", async () => {
  await assert.rejects(
    requestConnectLink(REQUEST, "hubspot", refusal(409, "connect_request_closed")),
    (error: unknown) => {
      assert.ok(error instanceof CrmConnectError);
      assert.equal(error.code, "connect_request_closed");
      assert.equal(
        error.message,
        "This connect card is no longer open — the CRM may already be connected.",
      );
      return true;
    },
  );
});

test("an unknown proposal surfaces the backend's code", async () => {
  await assert.rejects(fetchCrmProposal("p1", refusal(404, "crm_proposal_not_found")), {
    message: "crm_proposal_not_found",
  });
});

test("a Settings connect link names the page's workspace and a switched workspace is typed", async () => {
  let header: string | null = "unset";
  const answer = (async (_input: RequestInfo | URL, init?: RequestInit) => {
    header = new Headers(init?.headers).get("X-Clue-Page-Workspace");
    return new Response(JSON.stringify({ redirectUrl: "https://example.test/x", expiresAt: null }), {
      status: 200,
    });
  }) as typeof fetch;
  assert.equal(await requestConnectLink(REQUEST, "hubspot", answer, "ws_1"), "https://example.test/x");
  assert.equal(header, "ws_1");
  await requestConnectLink(REQUEST, "hubspot", answer);
  assert.equal(header, null);
  await assert.rejects(
    requestConnectLink(REQUEST, "hubspot", refusal(409, "WORKSPACE_CHANGED"), "ws_1"),
    (error: unknown) => error instanceof CrmConnectError && error.code === "WORKSPACE_CHANGED",
  );
});
