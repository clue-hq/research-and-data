import assert from "node:assert/strict";
import test from "node:test";
import { knowledgeBreadcrumb } from "./knowledge-breadcrumb";

test("a foldered document reads as its folder and its file", () => {
  assert.deepEqual(knowledgeBreadcrumb("design/Design.md"), [
    { kind: "folder", label: "Design" },
    { kind: "file", label: "Design.md" },
  ]);
  assert.deepEqual(knowledgeBreadcrumb("company/Overview.md"), [
    { kind: "folder", label: "Company" },
    { kind: "file", label: "Overview.md" },
  ]);
});

test("the file segment keeps the file's real name, extension and all", () => {
  const trail = knowledgeBreadcrumb("company/brand-kit.md");
  assert.deepEqual(trail.at(-1), { kind: "file", label: "brand-kit.md" });
});

test("folder names are humanized from the path, not looked up in a table", () => {
  assert.deepEqual(knowledgeBreadcrumb("audience_research/icp-notes.md"), [
    { kind: "folder", label: "Audience Research" },
    { kind: "file", label: "icp-notes.md" },
  ]);
  // Already-capitalized and multi-word segments survive unchanged.
  assert.deepEqual(knowledgeBreadcrumb("Proof/Case studies.md")[0], {
    kind: "folder",
    label: "Proof",
  });
});

test("nested folders each get a segment — the trail is the real path", () => {
  assert.deepEqual(knowledgeBreadcrumb("product/pricing/Tiers.md"), [
    { kind: "folder", label: "Product" },
    { kind: "folder", label: "Pricing" },
    { kind: "file", label: "Tiers.md" },
  ]);
});

test("a root-level document invents no parent folder", () => {
  assert.deepEqual(knowledgeBreadcrumb("Overview.md"), [
    { kind: "file", label: "Overview.md" },
  ]);
});

test("empty and malformed paths degrade to nothing, never to a fiction", () => {
  assert.deepEqual(knowledgeBreadcrumb(""), []);
  assert.deepEqual(knowledgeBreadcrumb("   "), []);
  assert.deepEqual(knowledgeBreadcrumb("///"), []);
  // Redundant separators collapse rather than minting blank crumbs.
  assert.deepEqual(knowledgeBreadcrumb("/design//Design.md/"), [
    { kind: "folder", label: "Design" },
    { kind: "file", label: "Design.md" },
  ]);
});

test("a percent-encoded route path is decoded before it is shown", () => {
  // `?file=design%2FDesign.md` is how this arrives on the URL; a breadcrumb
  // that rendered the escape would be showing route plumbing to a reader.
  assert.deepEqual(knowledgeBreadcrumb("design%2FDesign.md"), [
    { kind: "folder", label: "Design" },
    { kind: "file", label: "Design.md" },
  ]);
});

test("a path with no file segment still names what it knows", () => {
  assert.deepEqual(knowledgeBreadcrumb("design/"), [
    { kind: "file", label: "design" },
  ]);
});
