import assert from "node:assert/strict";
import { test } from "node:test";
import { brandContextLanding, pickSelectedDocument } from "./knowledge-selection";

const doc = (path: string) => ({ body: "", folderId: path.split("/")[0], id: path, name: path, path, updatedLabel: "Today" });
const documents = [doc("company/overview.md"), doc("product/catalog.md"), doc("product/proxon.md")];

test("Brand context opens on the company overview unless the link names a section", () => {
  assert.deepEqual(brandContextLanding({}), { section: "knowledge", filePath: "company/overview.md" });
  assert.deepEqual(brandContextLanding({ section: "colors" }), { section: "colors", filePath: undefined });
  assert.deepEqual(brandContextLanding({ section: "knowledge", file: "product/proxon.md" }), { section: "knowledge", filePath: "product/proxon.md" });
  assert.deepEqual(brandContextLanding({ section: "nonsense" }), { section: "knowledge", filePath: "company/overview.md" });
});

test("a document that is gone falls back to the catalog, an unset choice to the first document", () => {
  assert.equal(pickSelectedDocument(documents, "product/proxon.md")?.path, "product/proxon.md");
  assert.equal(pickSelectedDocument(documents, "product/proxon-platform.md")?.path, "product/catalog.md");
  assert.equal(pickSelectedDocument(documents, "")?.path, "company/overview.md");
  assert.equal(pickSelectedDocument([doc("company/overview.md")], "product/gone.md")?.path, "company/overview.md");
  assert.equal(pickSelectedDocument([], "product/gone.md"), undefined);
});
