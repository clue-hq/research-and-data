import assert from "node:assert/strict";
import test from "node:test";
import { ClueApiError } from "@/features/accounts/data/clue-api-error";
import { readProjectDocument, readProjectDocuments } from "./project-document-queries";

const document = {
  id: "document/1", path: "project/plan.md", kind: "project-plan", title: "Plan",
  version: 1, status: "ready", updated_at: "2026-09-14T08:00:00Z", icp_key: null,
  markdown: "# Original\n\nKeep `code` and **formatting**.", front_matter: { kind: "project-plan" },
};

test("browser document reads use the scoped BFF, preserve bytes and support abort", async () => {
  const calls: string[] = [];
  const signal = new AbortController().signal;
  const request: typeof fetch = async (url, init) => {
    calls.push(String(url));
    assert.equal(init?.signal, signal);
    assert.equal(init?.cache, "no-store");
    return Response.json({ data: calls.length === 1 ? { documents: [document] } : document });
  };
  const list = await readProjectDocuments("project/a", signal, request);
  const detail = await readProjectDocument("project/a", list[0].id, signal, request);
  assert.deepEqual(calls, ["/api/projects/project%2Fa/documents", "/api/projects/project%2Fa/documents/document%2F1"]);
  assert.equal(detail.markdown, document.markdown);
  assert.equal(detail.version, 1);
  assert.deepEqual(detail.frontMatter, document.front_matter);
});

test("empty documents differ from malformed, unavailable and access-refused reads", async () => {
  assert.deepEqual(await readProjectDocuments("p", undefined, async () => Response.json({ data: { documents: [] } })), []);
  for (const status of [401, 403, 404, 503]) {
    await assert.rejects(readProjectDocuments("p", undefined, async () => Response.json({ error: { code: "REFUSED" } }, { status })), (error: unknown) => {
      assert.ok(error instanceof ClueApiError);
      assert.equal(error.status, status);
      return true;
    });
  }
  await assert.rejects(readProjectDocument("p", "d", undefined, async () => Response.json({ data: { ...document, version: "one" } })), (error: unknown) => {
    assert.ok(error instanceof ClueApiError);
    assert.equal(error.code, "DOCUMENT_DETAIL_INVALID");
    return true;
  });
});

test("an aborted read stays aborted instead of becoming a user-facing service error", async () => {
  const controller = new AbortController();
  controller.abort();
  const error = new DOMException("Aborted", "AbortError");
  await assert.rejects(readProjectDocuments("p", controller.signal, async () => { throw error; }), (cause: unknown) => cause === error);
});
