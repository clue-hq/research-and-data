import assert from "node:assert/strict";
import test from "node:test";
import { brandContextFixture } from "../data/brand-context.fixture";
import {
  BrandContextWorkspaceSchema,
  parseKnowledgeMarkdown,
} from "./brand-context";

test("the Brand Context fixture satisfies the backend response schema", () => {
  const workspace = BrandContextWorkspaceSchema.parse(brandContextFixture);

  assert.equal(workspace.id, "clue-brand-context");
  assert.ok(workspace.colorGroups.length >= 3);
  assert.ok(workspace.assets.length >= 5);
  assert.equal(
    workspace.knowledgeFolders[0].documents[0].path,
    "company/Overview.md",
  );
});

test("knowledge markdown becomes ordered presentation blocks", () => {
  const blocks = parseKnowledgeMarkdown(
    "# Company\n\nA short description.\n\n- Founded: 2016\n- Industry: Software",
  );

  assert.deepEqual(blocks, [
    { depth: 1, text: "Company", type: "heading" },
    { text: "A short description.", type: "paragraph" },
    { items: ["Founded: 2016", "Industry: Software"], type: "list" },
  ]);
});
