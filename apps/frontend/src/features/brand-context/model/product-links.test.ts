import assert from "node:assert/strict";
import { test } from "node:test";
import { canLinkProducts, linkedProductNames, productOfPage } from "./product-links";

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

test("only Product-folder documents can name products, and never the generated catalog", () => {
  assert.equal(canLinkProducts({ ...base, id: "p", folderId: "product", kind: "product-research", version: 1 }), true);
  assert.equal(canLinkProducts({ ...base, id: "n", folderId: "product", kind: "note", version: 1 }), true);
  assert.equal(canLinkProducts({ ...base, id: "c", folderId: "product", generated: true, version: 1 }), false);
  assert.equal(canLinkProducts({ ...base, id: "o", folderId: "company", path: "company/overview.md", version: 1 }), false);
  assert.equal(canLinkProducts({ ...base, id: "a", folderId: "audience", path: "audience/icp.md", version: 1 }), false);
  assert.equal(canLinkProducts({ ...base, id: "d", folderId: "product" }), false); // not a stored version
});
