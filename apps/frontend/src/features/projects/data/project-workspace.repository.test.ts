import assert from "node:assert/strict";
import test from "node:test";
import {
  getProjectHome,
  getProjectWorkspace,
} from "./project-workspace.repository";

test("project fixtures satisfy the backend handoff contract", async () => {
  const [home, project] = await Promise.all([
    getProjectHome(),
    getProjectWorkspace("10m-landing-page-campaign"),
  ]);

  assert.equal(home.defaultBrandId, "brand-clue-demo");
  assert.ok(home.composerCapabilities.contextRefs);
  assert.ok(project.artifacts.every((artifact) => artifact.originThreadId));
  assert.ok(project.artifacts.every((artifact) => artifact.originRunId));
  assert.ok(project.models.some((model) => model.id === project.defaultModelId));
  assert.equal(home.suggestions.length, 3);
  assert.ok(home.suggestions.every((suggestion) => suggestion.length > 0));
});
