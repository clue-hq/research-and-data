import assert from "node:assert/strict";
import test from "node:test";
import { brandContextFixture } from "../data/brand-context.fixture";
import {
  BrandContextWorkspaceSchema,
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
