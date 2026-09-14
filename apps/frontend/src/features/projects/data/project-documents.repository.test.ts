import assert from "node:assert/strict";
import test from "node:test";
import { ClueApiError, type fetchRead } from "@/features/accounts/data/frontend-api";
import { getProjectDocument, listProjectDocuments } from "./project-documents.repository";
import { saveProjectDocument } from "./project-document-actions";

const wire = {
  id: "document/1", path: "project/plan.md", kind: "project-plan", title: "Plan", version: 1,
  status: "ready", updated_at: "2026-09-13T08:00:00Z", icp_key: null,
  markdown: "# Plan\n\nOriginal.", front_matter: { kind: "project-plan" },
};

test("list and detail use scoped, encoded server reads and retain the Markdown body", async () => {
  const calls: string[] = [];
  const read: typeof fetchRead = async (path) => {
    calls.push(path);
    return path.endsWith("/documents") ? { data: { documents: [wire] } } : { data: wire };
  };
  const documents = await listProjectDocuments("project/a", read);
  const detail = await getProjectDocument("project/a", documents[0].id, read);
  assert.deepEqual(calls, ["/projects/project%2Fa/documents", "/projects/project%2Fa/documents/document%2F1"]);
  assert.equal(detail.markdown, wire.markdown);
  assert.deepEqual(detail.frontMatter, wire.front_matter);
  assert.equal(detail.updatedAt, wire.updated_at);
  assert.equal(detail.icpKey, null);
});

test("empty lists are allowed but refused or malformed reads never become fixtures", async () => {
  assert.deepEqual(await listProjectDocuments("p", async () => ({ data: { documents: [] } })), []);
  await assert.rejects(listProjectDocuments("p", async () => ({ data: {} })));
  for (const status of [401, 403, 404, 503]) {
    await assert.rejects(getProjectDocument("p", "d", async () => {
      throw new ClueApiError("private backend details", { status, code: "BACKEND_CODE", requestId: "req-1" });
    }), (error: unknown) => {
      assert.ok(error instanceof ClueApiError);
      assert.equal(error.status, status);
      assert.equal(error.requestId, "req-1");
      assert.doesNotMatch(error.message, /private backend/);
      return true;
    });
  }
});

test("consecutive saves use returned immutable version IDs and never mutate the original", async () => {
  const original = await getProjectDocument("p", wire.id, async () => ({ data: wire }));
  const body = "  # Edited\n\nKeep whitespace and `code`.\n";
  const calls: { url: string; payload: unknown }[] = [];
  const request: typeof fetch = async (url, init) => {
    assert.equal(init?.method, "PUT");
    assert.equal(init?.cache, "no-store");
    calls.push({ url: String(url), payload: JSON.parse(String(init?.body)) });
    return Response.json({ data: { ...wire, id: `document/${calls.length + 1}`, version: calls.length + 1, markdown: body } });
  };
  const saved = await saveProjectDocument("project/a", original, body, request);
  await saveProjectDocument("project/a", saved, body, request);
  assert.deepEqual(calls, [
    { url: "/api/projects/project%2Fa/documents/document%2F1", payload: { body, expectedRevision: 1 } },
    { url: "/api/projects/project%2Fa/documents/document%2F2", payload: { body, expectedRevision: 2 } },
  ]);
  assert.equal(original.version, 1);
  assert.equal(original.markdown, wire.markdown);
  assert.equal(saved.markdown, body);
});

test("save conflicts and permission refusals stay actionable without retrying or replacing the draft", async () => {
  const original = await getProjectDocument("p", wire.id, async () => ({ data: wire }));
  for (const status of [401, 403, 409, 404, 422, 503]) {
    for (const envelope of ["error", "detail"]) {
      let calls = 0;
      await assert.rejects(saveProjectDocument("p", original, "# My draft", async () => {
        calls++;
        return Response.json({ [envelope]: { code: "DOCUMENT_REVISION_CONFLICT", message: "private info" } }, {
          status, headers: { "X-Request-Id": "req-save" },
        });
      }), (error: unknown) => {
        assert.ok(error instanceof ClueApiError);
        assert.equal(error.status, status);
        assert.equal(error.requestId, "req-save");
        assert.equal(error.code, "DOCUMENT_REVISION_CONFLICT");
        if (status === 409) assert.match(error.message, /newer version.*changes are still here/);
        if (status === 401 || status === 403) assert.match(error.message, /permission to edit/);
        return true;
      });
      assert.equal(calls, 1);
      assert.equal(original.markdown, wire.markdown);
    }
  }
});

test("a failed connection or non-JSON proxy error retains a retryable save error", async () => {
  const original = await getProjectDocument("p", wire.id, async () => ({ data: wire }));
  for (const request of [
    async () => { throw new Error("private hostname"); },
    async () => new Response("proxy unavailable", { status: 502 }),
  ]) {
    await assert.rejects(saveProjectDocument("p", original, "# Draft", request), (error: unknown) => {
      assert.ok(error instanceof ClueApiError);
      assert.equal(error.status, 502);
      assert.match(error.message, /changes are still here/);
      return true;
    });
  }
});

test("an unreadable successful save cannot replace the current document with unverified data", async () => {
  const original = await getProjectDocument("p", wire.id, async () => ({ data: wire }));
  for (const response of [Response.json({ data: { id: "new-id" } }), new Response("truncated")]) {
    await assert.rejects(saveProjectDocument("p", original, "# Draft", async () => response), (error: unknown) => {
      assert.ok(error instanceof ClueApiError);
      assert.equal(error.code, "DOCUMENT_SAVE_UNCONFIRMED");
      assert.match(error.message, /Could not confirm the save/);
      return true;
    });
    assert.equal(original.id, wire.id);
    assert.equal(original.markdown, wire.markdown);
  }
});
