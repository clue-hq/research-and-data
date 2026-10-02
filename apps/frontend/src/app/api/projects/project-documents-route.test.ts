import assert from "node:assert/strict";
import test from "node:test";
import { ClueAuthenticationError } from "@/auth/errors";
import { handleProjectDocuments } from "./project-documents-handler";
import { GET as listRoute } from "./[projectId]/documents/route";
import { GET as detailRoute, PUT as saveRoute } from "./[projectId]/documents/[documentId]/route";

const origin = "http://localhost:3040";
const target = { projectId: "project/a", documentId: "doc/1" };
function request(body = JSON.stringify({ body: "# Plan\n", expectedRevision: 1 }), from: string | null = origin) {
  return new Request(`${origin}/api/projects/p/documents/d`, {
    method: "PUT", body,
    headers: { ...(from ? { Origin: from } : {}), "Content-Type": "application/json", Authorization: "spoof", "X-Clue-Workspace-Id": "foreign" },
  });
}
const defaults = { authenticationEnabled: () => true, appOrigin: () => origin };

test("BFF reads forward exact backend envelopes without caching or taking browser credentials", async () => {
  for (const current of [{ projectId: target.projectId }, target]) {
    const response = await handleProjectDocuments(new Request(`${origin}/api/projects/p/documents`), current, {
      ...defaults,
      requestBackend: async (path, init) => {
        assert.equal(path, `/frontend/v1/projects/project%2Fa/documents${"documentId" in current ? "/doc%2F1" : ""}`);
        assert.equal(init.method, "GET");
        assert.equal(init.cache, "no-store");
        return Response.json({ data: { example: "wire envelope" } });
      },
    });
    assert.equal(response.status, 200);
    assert.equal(response.headers.get("Cache-Control"), "no-store");
    assert.deepEqual(await response.json(), { data: { example: "wire envelope" } });
  }
});

test("BFF PUT translates revision only; Markdown bytes and new version response are preserved", async () => {
  const body = "  # Plan\n\nKeep spacing.\n";
  const response = await handleProjectDocuments(request(JSON.stringify({ body, expectedRevision: 7 })), target, {
    ...defaults,
    requestBackend: async (path, init) => {
      assert.equal(path, "/frontend/v1/projects/project%2Fa/documents/doc%2F1");
      assert.equal(init.method, "PUT");
      assert.deepEqual(JSON.parse(String(init.body)), { body, expected_revision: 7 });
      const headers = new Headers(init.headers);
      assert.equal(headers.get("authorization"), null);
      assert.equal(headers.get("x-clue-workspace-id"), null);
      return Response.json({ data: { id: "doc-8", version: 8, markdown: body } });
    },
  });
  assert.deepEqual(await response.json(), { data: { id: "doc-8", version: 8, markdown: body } });
});

test("origin, authentication configuration and invalid updates refuse before upstream work", async () => {
  const cases = [
    { input: request(), enabled: false, status: 503 },
    { input: request(undefined, "https://foreign.example"), status: 403 },
    { input: request(undefined, null), status: 403 },
    { input: request("{"), status: 400 },
    { input: request(JSON.stringify({ body: "# Plan", expectedRevision: 0 })), status: 422 },
    { input: request(JSON.stringify({ body: "# Plan", expectedRevision: 1, workspace_id: "foreign" })), status: 422 },
  ];
  for (const entry of cases) {
    const response = await handleProjectDocuments(entry.input, target, {
      ...defaults, authenticationEnabled: () => entry.enabled ?? true,
      requestBackend: async () => { throw new Error("must never forward"); },
    });
    assert.equal(response.status, entry.status);
    assert.equal(response.headers.get("Cache-Control"), "no-store");
  }
});

test("backend permission, not-found and conflict statuses and bodies pass through verbatim", async () => {
  for (const status of [401, 403, 404, 409, 422, 503]) {
    const body = JSON.stringify({ detail: { code: status === 409 ? "DOCUMENT_REVISION_CONFLICT" : "REFUSED", message: "refused" } });
    const response = await handleProjectDocuments(request(), target, {
      ...defaults,
      requestBackend: async () => new Response(body, { status, headers: {
        "Content-Type": "application/json", "X-Request-Id": "req-1", "Set-Cookie": "private-cookie", "Cache-Control": "public",
      } }),
    });
    assert.equal(response.status, status);
    assert.equal(await response.text(), body);
    assert.equal(response.headers.get("X-Request-Id"), "req-1");
    assert.equal(response.headers.get("Set-Cookie"), null);
    assert.equal(response.headers.get("Cache-Control"), "no-store");
  }
});

test("session permission errors keep status; unexpected faults expose no internal details", async () => {
  for (const status of [401, 403, 502]) {
    const response = await handleProjectDocuments(request(), target, {
      ...defaults,
      requestBackend: async () => {
        if (status === 502) throw new Error("database secret");
        throw new ClueAuthenticationError("Membership required", { status, code: "AUTH_REQUIRED", requestId: "req-auth" });
      },
    });
    assert.equal(response.status, status);
    assert.doesNotMatch(await response.text(), /database secret/);
  }
});

test("Next route exports call the guarded document handler", async (t) => {
  const previous = process.env.CLUE_AUTH_ENABLED;
  process.env.CLUE_AUTH_ENABLED = "false";
  t.after(() => {
    if (previous === undefined) delete process.env.CLUE_AUTH_ENABLED;
    else process.env.CLUE_AUTH_ENABLED = previous;
  });
  const params = Promise.resolve(target);
  for (const route of [listRoute, detailRoute, saveRoute]) {
    const response = await route(request(), { params });
    assert.equal(response.status, 503);
    assert.equal((await response.json()).error.code, "AUTHENTICATION_NOT_CONFIGURED");
  }
});
