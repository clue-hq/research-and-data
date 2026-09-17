import assert from "node:assert/strict";
import test from "node:test";
import type { WebPageSummary } from "../engine/webDocuments";
import { resolveActivePageId } from "./use-web-editing-session";

// F5 task 18: the session owns which page of a multi-page web document the
// canvas renders. The rule is pure — the requested page when the loaded
// document still has it, the first page otherwise, and nothing at all when the
// document has no pages — so a reload that drops the active page falls back
// instead of asking the render seam for a page that no longer exists.

const PAGES: WebPageSummary[] = [
  { id: "page_home", name: "Home", route: "/" },
  { id: "page_pricing", name: "Pricing", route: "/pricing" },
];

test("no pages resolves to no active page", () => {
  assert.equal(resolveActivePageId(undefined, null), null);
  assert.equal(resolveActivePageId([], null), null);
  assert.equal(resolveActivePageId([], "page_home"), null);
});

test("nothing requested resolves to the first page", () => {
  assert.equal(resolveActivePageId(PAGES, null), "page_home");
});

test("a requested page the document still has is honoured", () => {
  assert.equal(resolveActivePageId(PAGES, "page_pricing"), "page_pricing");
});

test("a requested page the reloaded document dropped falls back to the first", () => {
  assert.equal(resolveActivePageId(PAGES, "page_deleted"), "page_home");
  // The single-page document behaves exactly as it did before task 18.
  assert.equal(resolveActivePageId([PAGES[0]], "page_pricing"), "page_home");
});
