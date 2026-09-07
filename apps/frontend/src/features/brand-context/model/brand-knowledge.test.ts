import assert from "node:assert/strict";
import { test } from "node:test";

import { KnowledgeTreeSchema, toKnowledgeFolders } from "./brand-knowledge";

const tree = KnowledgeTreeSchema.parse({
  brandId: "brd_1",
  folders: [
    { key: "company", label: "Company", documents: [
      { id: "doc-1", path: "company/overview.md", title: "Insight Health overview", kind: "company-overview", version: 2, status: "ready", updatedAt: "2026-09-08T03:55:00Z", productId: null, icpKey: null },
    ] },
    { key: "product", label: "Product", documents: [] },
    { key: "audience", label: "Audience", documents: [
      { id: "doc-2", path: "audience/icp-gi-groups.md", title: "GI groups", kind: "icp-definition", version: 1, status: "proposed", updatedAt: "2026-09-08T03:55:00Z", productId: null, icpKey: "gi-groups" },
    ] },
    { key: "proof", label: "Proof", documents: [] },
  ],
});

test("folders map onto the dummy shape in wire order, keeping empty folders", () => {
  const folders = toKnowledgeFolders(tree, new Map([["doc-1", "# Insight Health overview\n\nBody."]]));
  assert.deepEqual(folders.map((f) => [f.id, f.label, f.documents.length]), [
    ["company", "Company", 1], ["product", "Product", 0], ["audience", "Audience", 1], ["proof", "Proof", 0],
  ]);
  const [overview] = folders[0].documents;
  assert.equal(overview.id, "doc-1");
  assert.equal(overview.folderId, "company");
  assert.equal(overview.name, "Insight Health overview");
  assert.equal(overview.path, "company/overview.md");
  assert.equal(overview.body, "# Insight Health overview\n\nBody.");
  assert.match(overview.updatedLabel, /^Updated /);
  // a document whose body was not read still lists, with an empty body
  assert.equal(folders[2].documents[0].body, "");
});

test("the tree schema refuses an unknown folder key and tolerates additive document keys", () => {
  assert.throws(() => KnowledgeTreeSchema.parse({ brandId: null, folders: [{ key: "memories", label: "M", documents: [] }] }));
  const parsed = KnowledgeTreeSchema.parse({ brandId: null, folders: [{ key: "proof", label: "Proof", documents: [{ id: "x", path: "proof/a.md", title: "A", kind: "customer-reviews", version: 1, status: "ready", updatedAt: "2026-09-08T00:00:00Z", productId: null, icpKey: null, extra: 1 }] }] });
  assert.equal(parsed.folders[0].documents[0].id, "x");
});
