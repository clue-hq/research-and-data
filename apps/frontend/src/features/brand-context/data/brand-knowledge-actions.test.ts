import assert from "node:assert/strict";
import { test } from "node:test";
import { saveKnowledgeDocument } from "./brand-knowledge-actions";

const document = { id: "old-id", version: 2, path: "company/overview.md", folderId: "company", body: "# Original", name: "Original", updatedLabel: "Today", bodyLoaded: true };

test("save sends the original revision and exact Markdown, then adopts the returned version", async () => {
  const body = "\n# Updated\n\n| A | B |\n| - | - |\n| x | y |\n";
  const result = await saveKnowledgeDocument(document, body, (async (url, init) => {
    assert.equal(url, "/api/clue/frontend/v1/brand-context/knowledge/documents/old-id");
    assert.equal(init?.method, "PUT");
    assert.deepEqual(JSON.parse(String(init?.body)), { body, expectedRevision: 2 });
    return Response.json({ id: "new-id", version: 3, path: document.path, title: "Updated", kind: "company-overview", status: "ready", updatedAt: "2026-09-12T00:00:00Z", productId: null, icpKey: null, markdown: body, frontMatter: {}, sources: [] });
  }) as typeof fetch);
  assert.equal(result.body, body);
  assert.equal(result.version, 3);
  assert.equal(result.id, "new-id");
  assert.equal(result.path, document.path);
  assert.equal(result.bodyLoaded, true);
});

test("save failures are actionable and do not change the original document", async () => {
  for (const [status, message] of [[409, /newer version/], [403, /permission/], [500, /try again/]] as const) {
    await assert.rejects(saveKnowledgeDocument(document, "changed", (async () => new Response(null, { status })) as typeof fetch), message);
  }
  await assert.rejects(saveKnowledgeDocument(document, "changed", (async () => { throw new TypeError("offline"); }) as typeof fetch), /Could not confirm/);
  await assert.rejects(saveKnowledgeDocument(document, "changed", (async () => Response.json({})) as typeof fetch), /Could not confirm/);
  assert.equal(document.body, "# Original");
});

test("generated documents and failed body reads cannot save an empty replacement", async () => {
  const neverFetch = (async () => { assert.fail("must not write"); }) as typeof fetch;
  await assert.rejects(saveKnowledgeDocument({ ...document, version: undefined }, "changed", neverFetch), /not available/);
  await assert.rejects(saveKnowledgeDocument({ ...document, bodyLoaded: false }, "changed", neverFetch), /not available/);
});
