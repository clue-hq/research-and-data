import assert from "node:assert/strict";
import { test } from "node:test";

import { readBrandKnowledgeFolders, readOnboardingStatus } from "./brand-knowledge.repository";

function fetchOf(routes: Record<string, unknown | Error>): typeof fetch {
  return (async (input: RequestInfo | URL) => {
    const path = String(input);
    const hit = Object.entries(routes).find(([key]) => path.endsWith(key));
    if (!hit) return new Response("nope", { status: 404 });
    if (hit[1] instanceof Error) throw hit[1];
    return new Response(JSON.stringify(hit[1]), { status: 200, headers: { "content-type": "application/json" } });
  }) as typeof fetch;
}

const TREE = {
  brandId: "brd_1",
  folders: [
    { key: "company", label: "Company", documents: [{ id: "doc-1", path: "company/overview.md", title: "Overview", kind: "company-overview", version: 1, status: "ready", updatedAt: "2026-09-08T00:00:00Z", productId: null, icpKey: null }] },
    { key: "product", label: "Product", documents: [{ id: "doc-2", path: "product/aura.md", title: "Aura", kind: "product-research", version: 1, status: "ready", updatedAt: "2026-09-08T00:00:00Z", productId: "prd_a", icpKey: null }] },
    { key: "audience", label: "Audience", documents: [] },
    { key: "proof", label: "Proof", documents: [] },
  ],
};

test("reads the tree, then every body in parallel, and maps to folders", async () => {
  const fetch = fetchOf({
    "/frontend/v1/brand-context/knowledge": TREE,
    "/knowledge/documents/doc-1": { id: "doc-1", path: "company/overview.md", title: "Overview", kind: "company-overview", version: 1, status: "ready", updatedAt: "2026-09-08T00:00:00Z", productId: null, icpKey: null, markdown: "# Overview\n", frontMatter: {}, sources: [] },
    "/knowledge/documents/doc-2": new Error("boom"),
  });
  const folders = await readBrandKnowledgeFolders(fetch);
  assert.equal(folders[0].documents[0].body, "# Overview\n");
  assert.equal(folders[1].documents[0].body, "");
  assert.equal(folders[1].documents[0].name, "Aura");
});

test("a refused tree yields no folders and never rejects", async () => {
  assert.deepEqual(await readBrandKnowledgeFolders(fetchOf({})), []);
  assert.deepEqual(await readBrandKnowledgeFolders(fetchOf({ "/frontend/v1/brand-context/knowledge": new Error("down") })), []);
});

test("the onboarding status parses and a refusal is null", async () => {
  const status = await readOnboardingStatus(fetchOf({ "/brand-context/onboarding/current": { runId: "r", status: "running", steps: [{ kind: "overview", subjectRef: null, phase: "fast", status: "completed", startedAt: "2026-09-08T00:00:00Z", finishedAt: "2026-09-08T00:01:00Z", costUsd: "0.5", failureCode: null }], costUsd: "0.5" } }));
  assert.equal(status?.status, "running");
  assert.equal(await readOnboardingStatus(fetchOf({})), null);
});
