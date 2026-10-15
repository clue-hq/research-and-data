import assert from "node:assert/strict";
import { test } from "node:test";
import {
  addProduct,
  linkDocumentProducts,
  mergeProducts,
  readBrandProducts,
  removeProduct,
  renameProduct,
  undoProductChange,
} from "./brand-products";

const change = {
  changeId: "chg-1", kind: "merge", text: "2 products merged into Proxon", productId: "prd_proxon",
  productName: "Proxon", pageDocumentId: null, pagePending: true, projectsUpdated: 1, projectsNeedingChoice: 0,
};

function recording(response: () => Response) {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const fetcher = (async (url: string, init?: RequestInit) => {
    calls.push({ url: String(url), init });
    return response();
  }) as typeof fetch;
  return { calls, fetcher };
}

test("each product action posts to its route and returns what the change did", async () => {
  const { calls, fetcher } = recording(() => Response.json(change));
  assert.equal((await addProduct({ name: "Proxon Agents", description: "Agents." }, fetcher)).text, change.text);
  await renameProduct("prd_a", "Proxon AI", fetcher);
  await mergeProducts({ productIds: ["prd_a", "prd_b"], intoProductId: "prd_proxon" }, fetcher);
  await mergeProducts({ productIds: ["prd_a"], newName: "Proxon" }, fetcher);
  await removeProduct("prd_a", fetcher);
  await undoProductChange("chg-1", fetcher);
  const base = "/api/clue/frontend/v1/brand-context";
  assert.deepEqual(calls.map((c) => [c.init?.method, c.url]), [
    ["POST", `${base}/products`],
    ["POST", `${base}/products/prd_a/rename`],
    ["POST", `${base}/products/merge`],
    ["POST", `${base}/products/merge`],
    ["POST", `${base}/products/prd_a/remove`],
    ["POST", `${base}/product-changes/chg-1/undo`],
  ]);
  assert.deepEqual(JSON.parse(String(calls[0].init?.body)), { name: "Proxon Agents", description: "Agents." });
  assert.deepEqual(JSON.parse(String(calls[2].init?.body)), { productIds: ["prd_a", "prd_b"], intoProductId: "prd_proxon" });
  assert.deepEqual(JSON.parse(String(calls[3].init?.body)), { productIds: ["prd_a"], newName: "Proxon" });
});

test("a refusal surfaces the platform's own message, and a dead network says so", async () => {
  const refused = recording(() =>
    Response.json({ error: { code: "PRODUCT_NAME_TAKEN", message: "the brand already has a product called Proxon" } }, { status: 409 }),
  );
  await assert.rejects(renameProduct("prd_a", "Proxon", refused.fetcher), /already has a product called Proxon/);
  const forbidden = recording(() => new Response(null, { status: 403 }));
  await assert.rejects(removeProduct("prd_a", forbidden.fetcher), /permission/);
  await assert.rejects(removeProduct("prd_a", (async () => { throw new TypeError("offline"); }) as typeof fetch), /Could not reach/);
});

test("the product list read never rejects: a refused read is no list", async () => {
  const ok = recording(() =>
    Response.json({ brandId: "brd", products: [{ productId: "prd_a", name: "Proxon", aliases: ["Observer"], pageDocumentId: "doc", pagePath: "product/proxon.md", pagePending: false }], recentChanges: [] }),
  );
  const products = await readBrandProducts(ok.fetcher);
  assert.equal(products?.products[0].name, "Proxon");
  assert.equal(ok.calls[0].url, "/frontend/v1/brand-context/products");
  assert.equal(await readBrandProducts(recording(() => new Response(null, { status: 500 })).fetcher), null);
});

test("linking a document to products re-saves its current body with the chosen ids", async () => {
  const document = { id: "doc-1", version: 2, path: "audience/notes.md", folderId: "audience", body: "# Notes", name: "Notes", updatedLabel: "Today", bodyLoaded: true };
  const { calls, fetcher } = recording(() =>
    Response.json({ id: "doc-2", version: 3, path: document.path, title: "Notes", kind: "note", status: "ready", updatedAt: "2026-10-15T00:00:00Z", productId: null, productIds: ["prd_a"], generated: false, icpKey: null, markdown: "# Notes", frontMatter: {}, sources: [] }),
  );
  const saved = await linkDocumentProducts(document, ["prd_a"], fetcher);
  assert.deepEqual(JSON.parse(String(calls[0].init?.body)), { body: "# Notes", expectedRevision: 2, productIds: ["prd_a"] });
  assert.equal(calls[0].init?.method, "PUT");
  assert.deepEqual(saved.productIds, ["prd_a"]);
});
