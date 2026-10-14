import assert from "node:assert/strict";
import { test } from "node:test";
import { linkedProductNames, productOfPage } from "./product-links";

const products = [
  { productId: "prd_a", name: "Proxon", aliases: [], pageDocumentId: "doc-page", pagePath: "product/proxon.md", pagePending: false },
  { productId: "prd_b", name: "Proxon Agents", aliases: [], pageDocumentId: null, pagePath: null, pagePending: true },
];
const base = { body: "", folderId: "product", name: "x", path: "product/x.md", updatedLabel: "Today" };

test("a product page belongs to the product whose page it is, and nothing else does", () => {
  assert.equal(productOfPage({ ...base, id: "doc-page", kind: "product-research" }, products)?.name, "Proxon");
  assert.equal(productOfPage({ ...base, id: "doc-page", kind: "product-catalog" }, products), undefined);
  assert.equal(productOfPage({ ...base, id: "doc-other", kind: "product-research" }, products), undefined);
});

test("a document names its products in list order and ignores ids no longer on the list", () => {
  assert.deepEqual(linkedProductNames({ ...base, id: "d", productIds: ["prd_b", "prd_gone", "prd_a"] }, products), ["Proxon", "Proxon Agents"]);
  assert.deepEqual(linkedProductNames({ ...base, id: "d" }, products), []);
});
